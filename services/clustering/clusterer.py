"""Event clustering service — assigns articles to events by semantic similarity.

For each newly embedded article, finds the nearest event by centroid cosine
similarity (>0.85 threshold) within a 72-hour time window. If no match exists,
creates a new event with status='candidate'.

Flow:
    articles (embedded, unclustered) → find nearest event → link or create → recompute centroid
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
import numpy as np

from services.clustering.embedder import _centroid, _cosine_similarity

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────────────────────────────────────


async def _get_unclustered_articles(
    conn: asyncpg.Connection, batch_size: int = 50
) -> list[asyncpg.Record]:
    """Fetch embedded articles not yet assigned to any event.

    Articles that have embeddings but no row in event_articles.
    """
    rows = await conn.fetch(
        """
        SELECT a.id::text, a.canonical_url, a.title, a.published_at,
               a.outlet_id::text, a.embedding::text AS embedding_str, a.created_at
        FROM articles a
        LEFT JOIN event_articles ea ON ea.article_id = a.id
        WHERE a.status = 'embedded'
          AND a.embedding IS NOT NULL
          AND ea.id IS NULL
        ORDER BY a.created_at
        LIMIT $1
        FOR UPDATE OF a SKIP LOCKED
        """,
        batch_size,
    )
    return rows


async def _get_recent_events_with_centroids(
    conn: asyncpg.Connection,
    since: datetime | None,
) -> list[asyncpg.Record]:
    """Get events with centroids, optionally filtered by time window.

If since is None (article has no published_at), returns all events.
    """
    if since is not None:
        rows = await conn.fetch(
            """
            SELECT id::text, canonical_title, centroid::text AS centroid_str,
                   article_count, outlet_count, status,
                   COALESCE(last_seen_at, created_at) AS last_seen_at
            FROM events
            WHERE COALESCE(last_seen_at, created_at) >= $1
              AND centroid IS NOT NULL
            ORDER BY COALESCE(last_seen_at, created_at) DESC
            LIMIT 200
            """,
            since,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id::text, canonical_title, centroid::text AS centroid_str,
                   article_count, outlet_count,
                   COALESCE(last_seen_at, created_at) AS last_seen_at, status
            FROM events
            WHERE centroid IS NOT NULL
            ORDER BY COALESCE(last_seen_at, created_at) DESC NULLS LAST
            LIMIT 200
            """
        )
    return rows


async def _find_nearest_event(
    conn: asyncpg.Connection,
    article_embedding: list[float],
    article_published_at: datetime | None,
    article_created_at: datetime,  # fallback anchor when published_at is NULL
    similarity_threshold: float,
    time_window_hours: int,
) -> asyncpg.Record | None:
    """Find the nearest event by centroid similarity within time window.

    Returns the best-matching event with similarity > threshold, or None.
    """
    if article_published_at is not None:
        anchor = article_published_at
    else:
        anchor = article_created_at  # fallback to db insert time

    since = anchor - timedelta(hours=time_window_hours)
    events = await _get_recent_events_with_centroids(conn, since)

    best_event: asyncpg.Record | None = None
    best_similarity: float = -1.0

    for event in events:
        centroid_str = event["centroid_str"]
        if not centroid_str:
            continue

        # Parse pgvector string format "[0.1, 0.2, ...]" into list[float]
        centroid = _parse_vector_string(centroid_str)
        if centroid is None:
            continue

        sim = _cosine_similarity(article_embedding, centroid)

        if sim > best_similarity:
            best_similarity = sim
            best_event = event

    if best_similarity >= similarity_threshold:
        return best_event

    return None


async def _create_event(
    conn: asyncpg.Connection,
    title: str,
    centroid: list[float],
    published_at: datetime | None,
) -> asyncpg.Record:
    """Create a new event with initial centroid and status='candidate'.

    Sets first_seen_at and last_seen_at to the article's published_at
    so time-window clustering works correctly from the start.
    """
    row = await conn.fetchrow(
        """
        INSERT INTO events (
            canonical_title, centroid, first_seen_at, last_seen_at,
            article_count, outlet_count, status, created_at, updated_at
        )
        VALUES ($1, $2::vector, $3, $3, 1, 1, 'candidate', $3, $3)
        RETURNING *
        """,
        title,
        str(centroid),
        published_at,
    )
    return row


async def _link_article_to_event(
    conn: asyncpg.Connection,
    event_id: str,
    article_id: str,
    relevance_score: float,
) -> None:
    """Link an article to an event via event_articles."""
    await conn.execute(
        """
        INSERT INTO event_articles (event_id, article_id, relevance_score)
        VALUES ($1, $2, $3)
        ON CONFLICT (event_id, article_id) DO UPDATE
        SET relevance_score = $3, assigned_at = now()
        """,
        event_id,
        article_id,
        relevance_score,
    )


async def _update_event_centroid(
    conn: asyncpg.Connection, event_id: str
) -> None:
    """Recompute and update the event centroid from all member articles.

    Also updates denormalized counts (article_count, outlet_count) and
    time window (first_seen_at, last_seen_at).
    """
    # Fetch all linked article embeddings + metadata
    rows = await conn.fetch(
        """
        SELECT a.embedding::text AS embedding_str, a.outlet_id, a.published_at
        FROM event_articles ea
        JOIN articles a ON a.id = ea.article_id
        WHERE ea.event_id = $1 AND a.embedding IS NOT NULL
        """,
        event_id,
    )

    if not rows:
        return

    embeddings: list[list[float]] = []
    unique_outlets: set[str] = set()
    first_seen: datetime | None = None
    last_seen: datetime | None = None

    for row in rows:
        emb = _parse_vector_string(row["embedding_str"])
        if emb:
            embeddings.append(emb)

        unique_outlets.add(str(row["outlet_id"]))
        pub = row["published_at"]
        if pub and isinstance(pub, datetime):
            if first_seen is None or pub < first_seen:
                first_seen = pub
            if last_seen is None or pub > last_seen:
                last_seen = pub

    if not embeddings:
        return

    new_centroid = _centroid(embeddings)

    await conn.execute(
        """
        UPDATE events
        SET centroid = $1::vector,
            article_count = $2,
            outlet_count = $3,
            first_seen_at = COALESCE($4, first_seen_at),
            last_seen_at = COALESCE($5, last_seen_at),
            updated_at = now()
        WHERE id = $6
        """,
        str(new_centroid),
        len(embeddings),
        len(unique_outlets),
        first_seen,
        last_seen,
        event_id,
    )


def _parse_vector_string(s: str | None) -> list[float] | None:
    """Parse a pgvector string like '[0.1,0.2,0.3]' into a list of floats."""
    if not s:
        return None
    try:
        # Strip brackets and split on commas
        cleaned = s.strip().lstrip("[").rstrip("]")
        return [float(x.strip()) for x in cleaned.split(",")]
    except (ValueError, AttributeError):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


async def cluster_batch(
    db_url: str | None = None,
    *,
    batch_size: int | None = None,
    similarity_threshold: float | None = None,
    time_window_hours: int | None = None,
) -> dict[str, Any]:
    """Cluster a batch of embedded but unassigned articles into events.

    Args:
        db_url: Postgres connection string. Reads from DATABASE_URL env if None.
        batch_size: Max articles per run. Defaults to 50.
        similarity_threshold: Cosine similarity threshold for same-event match.
                              Reads CLUSTERING_SIMILARITY_THRESHOLD from env (default 0.85).
        time_window_hours: Max hours between article and event for clustering.
                           Reads CLUSTERING_TIME_WINDOW_HOURS from env (default 72).

    Returns:
        Summary dict: {processed, clustered, events_created, errors}.
    """
    import os
    from dotenv import load_dotenv

    load_dotenv()

    if db_url is None:
        db_url = os.getenv("DATABASE_URL", "")

    if similarity_threshold is None:
        similarity_threshold = float(
            os.getenv("CLUSTERING_SIMILARITY_THRESHOLD", "0.85")
        )

    if time_window_hours is None:
        time_window_hours = int(
            os.getenv("CLUSTERING_TIME_WINDOW_HOURS", "72")
        )

    summary: dict[str, Any] = {
        "processed": 0,
        "clustered": 0,
        "events_created": 0,
        "events_joined": 0,
        "errors": [],
    }

    async with asyncpg.create_pool(db_url, min_size=1, max_size=3) as pool:
        async with pool.acquire() as conn:
            articles = await _get_unclustered_articles(conn, batch_size)

            if not articles:
                logger.info("No unclustered articles.")
                return summary

            logger.info("Clustering %d unclustered articles...", len(articles))
            summary["processed"] = len(articles)

            for article in articles:
                try:
                    emb = _parse_vector_string(article["embedding_str"])
                    if emb is None:
                        logger.warning(
                            "Article %s has no valid embedding, skipping",
                            article["id"],
                        )
                        continue

                    published_at = article["published_at"]

                    # Find nearest event
                    best_event = await _find_nearest_event(
                        conn,
                        emb,
                        published_at,
                        article["created_at"],  # fallback for NULL published_at
                        similarity_threshold,
                        time_window_hours,
                    )

                    if best_event is not None:
                        # Link to existing event
                        event_id = best_event["id"]
                        sim = _cosine_similarity(
                            emb,
                            _parse_vector_string(best_event["centroid_str"]) or [0.0] * 768,
                        )
                        await _link_article_to_event(conn, event_id, article["id"], sim)
                        await _update_event_centroid(conn, event_id)
                        summary["events_joined"] += 1
                        summary["clustered"] += 1

                        logger.debug(
                            "  ⊕ %s → event %s (sim=%.4f)",
                            article["title"][:60],
                            best_event["canonical_title"][:40],
                            sim,
                        )
                    else:
                        # Create new event
                        title = article["title"] or "Sem título"
                        new_event = await _create_event(
                            conn, title, emb, published_at
                        )
                        await _link_article_to_event(
                            conn, new_event["id"], article["id"], 1.0
                        )
                        summary["events_created"] += 1
                        summary["clustered"] += 1

                        logger.debug(
                            "  ✦ new event: %s",
                            title[:60],
                        )

                except Exception as exc:
                    summary["errors"].append(
                        {"article_id": article["id"], "error": str(exc)}
                    )
                    logger.error("Error clustering article %s: %s", article["id"], exc)

    logger.info(
        "Clustering batch complete: %d processed, %d clustered (%d joined, %d created), %d errors",
        summary["processed"],
        summary["clustered"],
        summary["events_joined"],
        summary["events_created"],
        len(summary["errors"]),
    )

    return summary