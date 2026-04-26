"""Tests for ai/clients.py and ai/router.py.

Verifies:
    - Client factories return AsyncOpenAI instances with correct base URLs.
    - task routing selects the correct primary provider/model pair.
    - call() returns 768-dim embeddings via Ollama.
    - call() returns valid JSON chat responses via Ollama mistral.
    - ai_runs audit rows are created on success and failure.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from openai import AsyncOpenAI

from ai.clients import (
    get_client,
    get_groq_client,
    get_nvidia_nim_client,
    get_ollama_client,
    get_openrouter_client,
)
from ai.router import _TASK_CONFIG, call, TaskName


# ──────────────────────────────────────────────────────────────────────────────
# Client factory tests
# ──────────────────────────────────────────────────────────────────────────────


class TestClientFactories:
    """Each factory returns an AsyncOpenAI with the correct base_url."""

    def test_ollama_client_returns_async_openai(self):
        client = get_ollama_client()
        assert isinstance(client, AsyncOpenAI)
        assert "/v1" in str(client.base_url)
        assert "11434" in str(client.base_url)

    def test_nim_client_reads_env_key(self, monkeypatch):
        monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nvapi-test123")
        client = get_nvidia_nim_client()
        assert isinstance(client, AsyncOpenAI)
        assert "integrate.api.nvidia.com" in str(client.base_url)

    def test_nim_client_fallback_key(self, monkeypatch):
        monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
        client = get_nvidia_nim_client()
        assert isinstance(client, AsyncOpenAI)

    def test_groq_client_reads_env_key(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
        client = get_groq_client()
        assert isinstance(client, AsyncOpenAI)
        assert "api.groq.com" in str(client.base_url)

    def test_openrouter_client_reads_env_key(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        client = get_openrouter_client()
        assert isinstance(client, AsyncOpenAI)
        assert "openrouter.ai" in str(client.base_url)


# ──────────────────────────────────────────────────────────────────────────────
# get_client() caching and validation
# ──────────────────────────────────────────────────────────────────────────────


class TestGetClient:
    """Caching behaviour and error cases."""

    def test_get_client_returns_same_instance(self):
        a = get_client("ollama")
        b = get_client("ollama")
        assert a is b

    def test_get_client_different_providers_different_instances(self):
        ollama = get_client("ollama")
        groq = get_client("groq")
        assert ollama is not groq

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            get_client("nonexistent")  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────────
# Task configuration tests
# ──────────────────────────────────────────────────────────────────────────────


class TestTaskConfig:
    """The task→provider map matches the spec in CLAUDE.md."""

    def test_embed_primary_is_ollama_nomic(self):
        primary = _TASK_CONFIG["embed"][0]
        assert primary == ("ollama", "nomic-embed-text")

    def test_extractor_fast_primary_is_ollama_mistral(self):
        primary = _TASK_CONFIG["extractor_fast"][0]
        assert primary == ("ollama", "mistral")

    def test_framing_analyst_primary_is_nim_mistral(self):
        primary = _TASK_CONFIG["framing_analyst"][0]
        assert primary == ("nvidia_nim", "mistral-small-4-119b")

    def test_summarize_primary_is_nim_deepseek(self):
        primary = _TASK_CONFIG["summarize"][0]
        assert primary == ("nvidia_nim", "deepseek-r1")

    def test_fallback_primary_is_openrouter_llama(self):
        primary = _TASK_CONFIG["fallback"][0]
        assert primary == ("openrouter", "llama-3.3-70b-instruct")

    def test_all_tasks_have_at_least_one_entry(self):
        for task_name in _TASK_CONFIG:
            assert len(_TASK_CONFIG[task_name]) >= 1, f"{task_name} has no entries"


# ──────────────────────────────────────────────────────────────────────────────
# route_call integration tests (require live Docker services)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestCallIntegration:
    """End-to-end tests hitting live Ollama and database.

    Skip with:  pytest -m "not integration"
    """

    @pytest.mark.asyncio
    async def test_embed_returns_768_dim(self):
        """Embedding via router should produce 768-dim vectors."""
        result = await call(
            "embed",
            input_texts=[
                "search_document: Governo aprova novo pacote de medidas económicas em Portugal"
            ],
            embedding_prefix="search_document",
            prompt_version="v1",
        )

        assert "error" not in result, f"Embed call failed: {result.get('error')}"
        assert "embeddings" in result
        assert len(result["embeddings"]) == 1
        assert len(result["embeddings"][0]) == 768, (
            f"Expected 768 dim, got {len(result['embeddings'][0])}"
        )
        assert result["provider"] == "ollama"
        assert result["model"] == "nomic-embed-text"

    @pytest.mark.asyncio
    async def test_chat_extractor_fast_returns_json(self):
        """Fast extraction via Ollama mistral should return valid JSON.

        Note: This is NOT the full extraction prompt — just a lightweight
        smoke test that the chat pipeline works end-to-end.
        """
        result = await call(
            "extractor_fast",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a JSON extractor. Extract the name and topic "
                        "from articles. Return ONLY valid JSON like:\n"
                        '{"name": "...", "topic": "..."}'
                    ),
                },
                {
                    "role": "user",
                    "content": "Title: Portugal aprova orçamento rectificativo devido à crise energética.",
                },
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            prompt_version="v1",
        )

        assert "error" not in result, f"Chat call failed: {result.get('error')}"
        assert "content" in result

        # Validate it's parseable JSON
        content = result["content"]
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # Models sometimes wrap in markdown — try to extract
            if "```" in content:
                block = content.split("```")[1]
                if block.startswith("json"):
                    block = block[4:]
                parsed = json.loads(block.strip())
            else:
                raise

        assert isinstance(parsed, dict), f"Expected JSON object, got: {content[:200]}"
        assert result["provider"] == "ollama"
        assert result["model"] == "mistral"

    @pytest.mark.asyncio
    async def test_call_with_force_provider(self):
        """force_provider + force_model should bypass the task config."""
        result = await call(
            "embed",
            input_texts=["Test force provider"],
            force_provider="ollama",
            force_model="nomic-embed-text",
            prompt_version="v1",
        )
        assert "error" not in result
        assert result["provider"] == "ollama"
        assert result["model"] == "nomic-embed-text"


# ──────────────────────────────────────────────────────────────────────────────
# ai_runs audit log verification
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestAuditLogging:
    """Every successful call must create an ai_runs row."""

    @pytest.mark.asyncio
    async def test_embed_creates_ai_runs_row(self):
        import asyncpg

        result = await call(
            "embed",
            input_texts=["Audit test embedding"],
            prompt_version="v1",
        )
        assert "error" not in result

        conn = await asyncpg.connect(os.getenv("DATABASE_URL", ""))
        try:
            row = await conn.fetchrow(
                "SELECT * FROM ai_runs WHERE status = $1 ORDER BY created_at DESC LIMIT 1",
                "completed",
            )
            assert row is not None, "No ai_runs row found after successful call"
            assert row["task_name"] == "embed"
            assert row["provider"] == "ollama"
            assert row["model_name"] == "nomic-embed-text"
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_failed_call_creates_ai_runs_row(self):
        """A failed call (bad provider) should log a failed ai_runs row."""
        result = await call(
            "embed",
            input_texts=["This should fail"],
            force_provider="nvidia_nim",
            force_model="nv-embedqa-e5-v5",
            prompt_version="v1",
        )
        # May succeed or fail depending on NIM key validity;
        # If it fails, check the audit row
        if "error" in result:
            import asyncpg

            conn = await asyncpg.connect(os.getenv("DATABASE_URL", ""))
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM ai_runs WHERE status = $1 ORDER BY created_at DESC LIMIT 1",
                    "failed",
                )
                assert row is not None, "No failed ai_runs row found"
                assert row["task_name"] == "embed"
            finally:
                await conn.close()