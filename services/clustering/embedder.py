"""Batch embedding service for article clustering.

Takes articles with status='pending' (normalized but not yet embedded),
generates 768-dim embeddings via Ollama nomic-embed-text (search_document prefix),
and stores them in articles.embedding.

Also detects lusa_likely by comparing article embeddings against a known
Lusa reference embedding (cosine similarity > 0.88 threshold).

Flow:
    articles (pending) → batch embed → store vector(768) → status='embedded'
"""

from __future__ import annotations

import logging
import math
from typing import Any

import asyncpg
import numpy as np
from openai import AsyncOpenAI

from ai.clients import get_client

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Embedding helpers
# ──────────────────────────────────────────────────────────────────────────────


async def _generate_embeddings(
    client: AsyncOpenAI,
    texts: list[str],
    model: str = "nomic-embed-text",
    prefix: str = "search_document",
) -> list[list[float]]:
    """Generate 768-dim embeddings for a batch of texts via Ollama.

    Applies the recommended search_document prefix to each text.
    """
    if not texts:
        return []

    prefixed_texts = [f"{prefix}: {t}" for t in texts]

    response = await client.embeddings.create(
        model=model,
        input=prefixed_texts,
    )

    return [e.embedding for e in response.data]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two embedding vectors."""
    a_np = np.array(a, dtype=np.float64)
    b_np = np.array(b, dtype=np.float64)

    dot = float(np.dot(a_np, b_np))
    norm_a = float(np.linalg.norm(a_np))
    norm_b = float(np.linalg.norm(b_np))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)


def _centroid(embeddings: list[list[float]]) -> list[float]:
    """Compute the centroid (mean) of a list of embedding vectors."""
    if not embeddings:
        return [0.0] * 768
    arr = np.array(embeddings, dtype=np.float64)
    mean = np.mean(arr, axis=0)
    return mean.tolist()


# ──────────────────────────────────────────────────────────────────────────────
# Lusa similarity detection
# ──────────────────────────────────────────────────────────────────────────────

# Pre-computed reference embedding for Lusa news agency content.
# This is a placeholder — in production, compute from known Lusa articles.
# We use a zero-vector with a distinctive pattern to avoid false matches
# until a real Lusa reference is loaded.
_LUSA_REFERENCE: list[float] | None = None


async def _get_lusa_reference() -> list[float] | None:
    """Get or fetch the Lusa reference embedding.

    In V1,05 computes the reference from the first Lusa-cited article found
    in the database. This means the reference improves over time.
    """
    global _LUSA_REFERENCE

    if _LUSA_REFERENCE is not None:
        return _LUSA_REFERENCE

    # Try to load existing Lusa reference from an article explicitly citing Lusa
    import os
    from dotenv import load_dotenv
    load_dotenv()

    conn = await asyncpg.connect(os.getenv("DATABASE_URL", ""))
    try:
        row = await conn.fetchrow(
            """
            SELECT embedding FROM articles
            WHERE lusa_cited = TRUE AND embedding IS NOT NULL
            LIMIT 1
            """
        )
        if row:
            vec_str = row["embedding"]
            # pgvector returns embedding as a string like "[0.1,0.2,...]"
            if isinstance(vec_str, str):
                import json as _json
                _LUSA_REFERENCE = _json.loads(vec_str)
            else:
                _LUSA_REFERENCE = list(vec_str)
            return _LUSA_REFERENCE
    finally:
        await conn.close()

    return None


async def _check_lusa_similarity(
    embedding: list[float],
    threshold: float = 0.88,
) -> bool:
    """Check if an article embedding is similar to known Lusa content."""
    lusa_ref = await _get_lusa_reference()
    if lusa_ref is None:
        return False

    sim = _cosine_similarity(embedding, lusa_ref)
    return sim >= threshold


# ──────────────────────────────────────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────────────────────────────────────


async def _get_unembedded_articles(
    conn: asyncpg.Connection, batch_size: int = 20
) -> list[asyncpg.Record]:
    """Fetch articles with status='pending' that need embedding."""
    rows = await conn.fetch(
        """
        SELECT id::text, cleaned_text, word_count, lusa_cited, canonical_url
        FROM articles
        WHERE status = 'pending'
        ORDER BY created_at
        LIMIT $1
        FOR UPDATE SKIP LOCKED
        """,
        batch_size,
    )
    return rows


async def _store_embedding(
    conn: asyncpg.Connection,
    article_id: str,
    embedding: list[float],
    lusa_likely: bool = False,
) -> None:
    """Store the embedding vector and update article status."""
    await conn.execute(
        """
        UPDATE articles
        SET embedding = $1::vector, lusa_likely = $2, status = 'embedded', updated_at = now()
        WHERE id = $3
        """,
        str(embedding),  # pgvector accepts string format "[0.1, 0.2, ...]"
        lusa_likely,
        article_id,
    )


async def _mark_article_failed(
    conn: asyncpg.Connection, article_id: str, error_msg: str
) -> None:
    """Mark an article as failed if embedding generation errors out."""
    await conn.execute(
        "UPDATE articles SET status = 'failed', error_msg = $1, updated_at = now() WHERE id = $2",
        error_msg,
        article_id,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


async def embed_batch(
    db_url: str | None = None,
    *,
    batch_size: int | None = None,
    lusa_threshold: float | None = None,
) -> dict[str, Any]:
    """Generate embeddings for a batch of pending articles.

    Args:
        db_url: Postgres connection string. Reads from DATABASE_URL env if None.
        batch_size: Max articles per run. Reads EMBEDDING_BATCH_SIZE from env (default 20).
        lusa_threshold: Cosine similarity threshold for lusa_likely detection.
                        Reads LUSA_SIMILARITY_THRESHOLD from env (default 0.88).

    Returns:
        Summary dict: {processed, embedded, failed, lusa_detected, errors}.
    """
    import os
    from dotenv import load_dotenv

    load_dotenv()

    if db_url is None:
        db_url = os.getenv("DATABASE_URL", "")

    if batch_size is None:
        batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "20"))

    if lusa_threshold is None:
        lusa_threshold = float(os.getenv("LUSA_SIMILARITY_THRESHOLD", "0.88"))

    summary: dict[str, Any] = {
        "processed": 0,
        "embedded": 0,
        "failed": 0,
        "lusa_detected": 0,
        "errors": [],
    }

    client = get_client("ollama")

    async with asyncpg.create_pool(db_url, min_size=1, max_size=3) as pool:
        async with pool.acquire() as conn:
            articles = await _get_unembedded_articles(conn, batch_size)

            if not articles:
                logger.info("No pending articles need embedding.")
                return summary

            logger.info("Embedding %d pending articles...", len(articles))
            summary["processed"] = len(articles)

            # Process in sub-batches for efficiency
            texts = [a["cleaned_text"] for a in articles]

            try:
                embeddings = await _generate_embeddings(client, texts)
            except Exception as exc:
                logger.error("Batch embedding failed: %s", exc)
                # Mark all as failed
                for a in articles:
                    await _mark_article_failed(
                        conn, a["id"], f"Embedding error: {exc}"
                    )
                summary["failed"] = len(articles)
                summary["errors"].append({"batch": "all", "error": str(exc)})
                return summary

            # Store embeddings + check Lusa similarity
            for i, article in enumerate(articles):
                try:
                    emb = embeddings[i]

                    lusa_likely = await _check_lusa_similarity(emb, lusa_threshold)

                    if lusa_likely:
                        summary["lusa_detected"] += 1

                    await _store_embedding(conn, article["id"], emb, lusa_likely)
                    summary["embedded"] += 1

                    logger.debug(
                        "  ✓ %s (%d words, lusa_likely=%s)",
                        article["canonical_url"][:80],
                        article["word_count"],
                        lusa_likely,
                    )
                except Exception as exc:
                    summary["failed"] += 1
                    await _mark_article_failed(conn, article["id"], str(exc))
                    summary["errors"].append(
                        {"article_id": article["id"], "error": str(exc)}
                    )
                    logger.error("Failed to embed article %s: %s", article["id"], exc)

    logger.info(
        "Embedding batch complete: %d processed, %d embedded, %d failed, %d lusa_likely",
        summary["processed"],
        summary["embedded"],
        summary["failed"],
        summary["lusa_detected"],
    )

    return summary