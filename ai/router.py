"""AI call router — task-aware dispatcher with fallback chains.

Every call routes to a provider/model pair based on the task type,
logs an ai_runs row for auditability, and falls back to alternate
providers on failure.

Task → model mapping (from CLAUDE.md):
    ================  ================================  ===============================
    Task              Primary                           Fallback
    ================  ================================  ===============================
    embed             Ollama nomic-embed-text            NVIDIA NIM nv-embedqa-e5-v5
    extractor_fast    Ollama mistral                    NVIDIA NIM llama-3.3-70b-instruct
    framing_analyst   NVIDIA NIM mistral-small-4-119b   Groq llama-3.3-70b-versatile
    summarize         NVIDIA NIM deepseek-r1            Groq llama-3.3-70b-versatile
    fallback          OpenRouter llama-3.3-70b-instruct  —
    ================  ================================  ===============================
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Literal

import asyncpg
from dotenv import load_dotenv
from openai.types.chat import ChatCompletion
from openai.types.create_embedding_response import CreateEmbeddingResponse

# Load .env at module level so tests can import without manual setup.
load_dotenv()

from ai.clients import get_client, ProviderName

TaskName = Literal["embed", "extractor_fast", "framing_analyst", "summarize", "fallback"]

# ──────────────────────────────────────────────────────────────────────────────
# Task configuration
# ──────────────────────────────────────────────────────────────────────────────

# Each task maps to a list of (provider, model) pairs in priority order.
# The router tries them sequentially until one succeeds.
_TASK_CONFIG: dict[TaskName, list[tuple[ProviderName, str]]] = {
    "embed": [
        ("ollama", "nomic-embed-text"),
        ("nvidia_nim", "nv-embedqa-e5-v5"),
    ],
    "extractor_fast": [
        ("ollama", "mistral"),
        ("nvidia_nim", "llama-3.3-70b-instruct"),
    ],
    "framing_analyst": [
        ("nvidia_nim", "mistral-small-4-119b"),
        ("groq", "llama-3.3-70b-versatile"),
    ],
    "summarize": [
        ("nvidia_nim", "deepseek-r1"),
        ("groq", "llama-3.3-70b-versatile"),
    ],
    "fallback": [
        ("openrouter", "llama-3.3-70b-instruct"),
    ],
}


async def _get_db_connection() -> asyncpg.Connection | None:
    """Get a database connection from the connection string.

    Returns None if DATABASE_URL isn't set or connection fails,
    so callers can proceed without audit logging.
    """
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        return None
    try:
        return await asyncpg.connect(db_url)
    except Exception:
        return None


def _render_prompt_hash(prompt_text: str) -> str:
    """SHA-256 of the rendered prompt for reproducibility tracking."""
    return hashlib.sha256(prompt_text.encode()).hexdigest()[:12]


# ──────────────────────────────────────────────────────────────────────────────
# Logging helpers
# ──────────────────────────────────────────────────────────────────────────────


async def _log_ai_run(
    conn: asyncpg.Connection | None,
    task_name: TaskName,
    provider: ProviderName,
    model_name: str,
    prompt_version: str,
    prompt_hash: str | None,
    input_token_count: int | None,
    output_token_count: int | None,
    latency_ms: int,
    cost_estimate: float | None,
    status: str,
    error_message: str | None,
    temperature: float | None,
    response_format: dict[str, Any] | None,
    raw_response: Any | None,
    article_id: str | None = None,
    event_id: str | None = None,
) -> str | None:
    """Insert an ai_runs row, or return None if DB is unavailable."""
    if conn is None:
        return None

    row = await conn.fetchrow(
        """
        INSERT INTO ai_runs (
            task_name, provider, model_name, prompt_version, prompt_hash,
            input_token_count, output_token_count, latency_ms, cost_estimate,
            status, error_message, temperature, response_format, raw_response,
            article_id, event_id
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9,
            $10, $11, $12, $13, $14::jsonb,
            $15, $16
        ) RETURNING id
        """,
        task_name,
        provider,
        model_name,
        prompt_version,
        prompt_hash,
        input_token_count,
        output_token_count,
        latency_ms,
        cost_estimate,
        status,
        error_message,
        temperature,
        json.dumps(response_format) if response_format else None,
        json.dumps(raw_response) if raw_response else None,
        article_id,
        event_id,
    )
    return row["id"]


# ──────────────────────────────────────────────────────────────────────────────
# Public API: call()
# ──────────────────────────────────────────────────────────────────────────────


async def call(
    task: TaskName,
    *,
    # ---- Embedding params ----
    input_texts: list[str] | None = None,
    embedding_prefix: str | None = None,
    # ---- Chat params ----
    messages: list[dict[str, str]] | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.1,
    response_format: dict[str, Any] | None = None,
    # ---- Audit params ----
    prompt_version: str = "v1",
    prompt_text: str | None = None,
    article_id: str | None = None,
    event_id: str | None = None,
    # ---- Tuning ----
    force_provider: ProviderName | None = None,
    force_model: str | None = None,
) -> dict[str, Any]:
    """Dispatch an AI call with fallback chain and audit logging.

    Returns a dict:
        - For embeddings: {"embeddings": [[float, ...], ...], ...}
        - For chat:        {"content": "...", "raw": ChatCompletion, ...}
        - On total failure: {"error": str, "task": ...}

    Raises no exceptions — always returns a dict with at least an "error" key
    on total failure so callers can handle gracefully.
    """
    start = time.monotonic()

    # Determine which provider/model pairs to try.
    if force_provider and force_model:
        chain = [(force_provider, force_model)]
    else:
        chain = _TASK_CONFIG.get(task, [("openrouter", "llama-3.3-70b-instruct")])

    conn: asyncpg.Connection | None = None
    last_error: str | None = None

    for provider, model in chain:
        try:
            client = get_client(provider)

            # ── Embedding path ──────────────────────────────────────────────
            if task == "embed":
                if not input_texts:
                    return {"error": "input_texts required for embed task", "task": task}

                # Apply embedding prefix if configured
                texts = input_texts
                if embedding_prefix:
                    texts = [f"{embedding_prefix}: {t}" for t in texts]

                resp: CreateEmbeddingResponse = await client.embeddings.create(
                    model=model,
                    input=texts,
                )
                elapsed = int((time.monotonic() - start) * 1000)

                # Write audit log
                conn = await _get_db_connection()
                try:
                    prompt_hash = _render_prompt_hash(prompt_text or texts[0])
                    await _log_ai_run(
                        conn,
                        task_name=task,
                        provider=provider,
                        model_name=model,
                        prompt_version=prompt_version,
                        prompt_hash=prompt_hash,
                        input_token_count=resp.usage.prompt_tokens if resp.usage else None,
                        output_token_count=resp.usage.total_tokens if resp.usage else None,
                        latency_ms=elapsed,
                        cost_estimate=None,  # Ollama is free; NIM cost TBD
                        status="completed",
                        error_message=None,
                        temperature=None,
                        response_format=None,
                        raw_response=resp.model_dump(),
                        article_id=article_id,
                        event_id=event_id,
                    )
                finally:
                    if conn:
                        await conn.close()

                return {
                    "embeddings": [e.embedding for e in resp.data],
                    "model": model,
                    "provider": provider,
                    "usage": resp.usage.model_dump() if resp.usage else None,
                    "latency_ms": elapsed,
                }

            # ── Chat path ───────────────────────────────────────────────────
            if not messages:
                return {"error": "messages required for chat tasks", "task": task}

            # Build kwargs — avoid sending None/empty response_format
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if response_format:
                kwargs["response_format"] = response_format

            chat_resp: ChatCompletion = await client.chat.completions.create(**kwargs)
            elapsed = int((time.monotonic() - start) * 1000)

            # Write audit log
            usage = chat_resp.usage
            raw_dump = chat_resp.model_dump()

            conn = await _get_db_connection()
            try:
                prompt_hash = _render_prompt_hash(prompt_text or "")
                await _log_ai_run(
                    conn,
                    task_name=task,
                    provider=provider,
                    model_name=model,
                    prompt_version=prompt_version,
                    prompt_hash=prompt_hash,
                    input_token_count=usage.prompt_tokens if usage else None,
                    output_token_count=usage.completion_tokens if usage else None,
                    latency_ms=elapsed,
                    cost_estimate=None,
                    status="completed",
                    error_message=None,
                    temperature=temperature,
                    response_format=response_format,
                    raw_response=raw_dump,
                    article_id=article_id,
                    event_id=event_id,
                )
            finally:
                if conn:
                    await conn.close()

            return {
                "content": chat_resp.choices[0].message.content or "",
                "model": model,
                "provider": provider,
                "usage": usage.model_dump() if usage else None,
                "latency_ms": elapsed,
                "raw": raw_dump,
            }

        except Exception as exc:
            last_error = f"[{provider}/{model}] {type(exc).__name__}: {exc}"

            # Log the failure
            try:
                if conn is None:
                    conn = await _get_db_connection()
                await _log_ai_run(
                    conn,
                    task_name=task,
                    provider=provider,
                    model_name=model,
                    prompt_version=prompt_version,
                    prompt_hash=_render_prompt_hash(prompt_text or ""),
                    input_token_count=None,
                    output_token_count=None,
                    latency_ms=int((time.monotonic() - start) * 1000),
                    cost_estimate=None,
                    status="failed",
                    error_message=last_error,
                    temperature=temperature if task != "embed" else None,
                    response_format=response_format if task != "embed" else None,
                    raw_response=None,
                    article_id=article_id,
                    event_id=event_id,
                )
            except Exception:
                pass  # DB logging should not prevent fallback
            finally:
                if conn:
                    try:
                        await conn.close()
                    except Exception:
                        pass
                    conn = None

            continue  # Try next fallback

    # All providers exhausted
    return {
        "error": last_error or f"No providers succeeded for task {task!r}",
        "task": task,
    }