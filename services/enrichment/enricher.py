"""Enrichment service — link source documents to events, compute Lusa metrics.

Takes events with status='candidate' or 'unreviewed', links them to
source_documents by topic/entity/time-overlap match, and computes
lusa_dependency for downstream scoring.

Flow:
    events (candidate/unreviewed) → link source_documents → event_documents
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────────────────────────────────────


async def _get_unenriched_events(
    conn: asyncpg.Connection, batch_size: int = 50
) -> list[asyncpg.Record]:
    """Fetch candidate/unreviewed events that haven't been enriched yet."""
    rows = await conn.fetch(
        """
        SELECT e.id::text, e.canonical_title, e.first_seen_at, e.last_seen_at,
               e.article_count, e.outlet_count, e.status
        FROM events e
        LEFT JOIN event_documents ed ON ed.event_id = e.id
        WHERE e.status IN ('candidate', 'unreviewed')
          AND ed.id IS NULL
        ORDER BY e.created_at
        LIMIT $1
        FOR UPDATE OF e SKIP LOCKED
        """,
        batch_size,
    )
    return rows


async def _get_event_entities(
    conn: asyncpg.Connection, event_id: str
) -> list[str]:
    """Get all entity names linked to an event's articles."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT en.name
        FROM entities en
        JOIN article_entities ae ON ae.entity_id = en.id
        JOIN event_articles ea ON ea.article_id = ae.article_id
        WHERE ea.event_id = $1
        LIMIT 100
        """,
        event_id,
    )
    return [r["name"] for r in rows]


async def _get_event_topics(
    conn: asyncpg.Connection, event_id: str
) -> list[str]:
    """Get all topics extracted from an event's articles."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT jsonb_array_elements_text(aa.topics) AS topic
        FROM article_analysis aa
        JOIN event_articles ea ON ea.article_id = aa.article_id
        WHERE ea.event_id = $1
        """,
        event_id,
    )
    return [r["topic"] for r in rows]


async def _get_event_document_refs(
    conn: asyncpg.Connection, event_id: str
) -> list[dict[str, Any]]:
    """Get document references explicitly cited by the event's articles."""
    rows = await conn.fetch(
        """
        SELECT aa.document_refs::text AS doc_refs_str
        FROM article_analysis aa
        JOIN event_articles ea ON ea.article_id = aa.article_id
        WHERE ea.event_id = $1
          AND aa.cites_document = TRUE
        LIMIT 50
        """,
        event_id,
    )
    refs: list[dict[str, Any]] = []
    import json as _json
    for row in rows:
        raw = row["doc_refs_str"]
        if raw:
            try:
                parsed = _json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, list):
                    refs.extend(parsed)
            except (json.JSONDecodeError, TypeError):
                pass
    return refs


async def _find_matching_documents(
    conn: asyncpg.Connection,
    entity_names: list[str],
    topics: list[str],
    since: datetime,
    until: datetime,
) -> list[asyncpg.Record]:
    """Find source documents matching entities, topics, or time window."""
    # Build a search across entity name matches, topic matches, and time overlap
    if not entity_names and not topics:
        return []

    # Build ILIKE clauses for entities
    entity_conditions: list[str] = []
    params: list[Any] = [since, until]
    param_idx = 3

    for name in entity_names[:20]:  # limit to prevent query explosion
        entity_conditions.append(f"sd.title ILIKE ${param_idx}")
        params.append(f"%{name}%")
        param_idx += 1
        entity_conditions.append(f"COALESCE(sd.body_text, '') ILIKE ${param_idx}")
        params.append(f"%{name}%")
        param_idx += 1

    # Build ILIKE clauses for topics
    topic_conditions: list[str] = []
    for topic in topics[:10]:
        topic_conditions.append(f"sd.title ILIKE ${param_idx}")
        params.append(f"%{topic}%")
        param_idx += 1

    all_conditions = entity_conditions + topic_conditions
    if not all_conditions:
        return []

    where_clause = " OR ".join(all_conditions)

    query = f"""
        SELECT DISTINCT sd.id::text, sd.title, sd.source_type, sd.published_at,
               sd.body_text
        FROM source_documents sd
        WHERE sd.published_at >= $1 AND sd.published_at <= $2
          AND ({where_clause})
        ORDER BY sd.published_at DESC
        LIMIT 20
    """

    rows = await conn.fetch(query, *params)
    return rows


async def _link_document_to_event(
    conn: asyncpg.Connection,
    event_id: str,
    document_id: str,
    matched_by: str,
) -> None:
    """Link a document to an event."""
    await conn.execute(
        """
        INSERT INTO event_documents (event_id, document_id, matched_by)
        VALUES ($1, $2, $3)
        ON CONFLICT (event_id, document_id) DO NOTHING
        """,
        event_id,
        document_id,
        matched_by,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


async def enrich_batch(
    db_url: str | None = None,
    *,
    batch_size: int | None = None,
    time_window_days: int = 30,
) -> dict[str, Any]:
    """Enrich a batch of unenriched events with source document links.

    Args:
        db_url: Postgres connection string. Reads from DATABASE_URL env if None.
        batch_size: Max events per run. Defaults to 50.
        time_window_days: Days before/after event to search for documents (default 30).

    Returns:
        Summary dict: {processed, enriched, documents_linked, errors}.
    """
    import os

    if db_url is None:
        db_url = os.getenv("DATABASE_URL", "")

    if batch_size is None:
        batch_size = int(os.getenv("ENRICHMENT_BATCH_SIZE", "50"))

    summary: dict[str, Any] = {
        "processed": 0,
        "enriched": 0,
        "documents_linked": 0,
        "errors": [],
    }

    async with asyncpg.create_pool(db_url, min_size=1, max_size=3) as pool:
        async with pool.acquire() as conn:
            events = await _get_unenriched_events(conn, batch_size)

            if not events:
                logger.info("No events need enrichment.")
                return summary

            logger.info("Enriching %d events...", len(events))
            summary["processed"] = len(events)

            for event in events:
                try:
                    event_id = event["id"]
                    first_seen = event["first_seen_at"]
                    last_seen = event["last_seen_at"]
                    now = datetime.now(timezone.utc)

                    since = (first_seen or now) - timedelta(days=time_window_days)
                    until = (last_seen or now) + timedelta(days=time_window_days)

                    entities = await _get_event_entities(conn, event_id)
                    topics = await _get_event_topics(conn, event_id)

                    docs = await _find_matching_documents(
                        conn, entities, topics, since, until
                    )

                    links_this_event = 0
                    for doc in docs:
                        await _link_document_to_event(
                            conn, event_id, doc["id"], "entity"
                        )
                        links_this_event += 1

                    if links_this_event > 0:
                        summary["enriched"] += 1
                        summary["documents_linked"] += links_this_event

                    logger.debug(
                        "  ✓ event %s: %d docs linked (%d entities, %d topics)",
                        event["canonical_title"][:50],
                        links_this_event,
                        len(entities),
                        len(topics),
                    )
                except Exception as exc:
                    summary["errors"].append(
                        {"event_id": event["id"], "error": str(exc)}
                    )
                    logger.error(
                        "Error enriching event %s: %s", event["id"], exc
                    )

    logger.info(
        "Enrichment complete: %d processed, %d enriched, %d docs linked",
        summary["processed"],
        summary["enriched"],
        summary["documents_linked"],
    )
    return summary