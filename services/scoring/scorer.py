"""Scoring service — compute coverage breadth, framing divergence, evidence density.

Takes events that have been enriched, computes per-event scores for the
five dimensions, creates undercoverage flags when thresholds are breached,
and stores everything in event_scores + undercoverage_flags.

Flow:
    events (enriched) → compute scores → event_scores + undercoverage_flags
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Score computation helpers
# ──────────────────────────────────────────────────────────────────────────────


async def _get_total_active_outlets(conn: asyncpg.Connection) -> int:
    """Count of currently active outlets in the system."""
    count = await conn.fetchval(
        "SELECT count(*) FROM outlets WHERE active = TRUE"
    )
    return count or 20  # safe fallback


async def _get_event_article_count(conn: asyncpg.Connection, event_id: str) -> int:
    """Number of articles linked to an event."""
    count = await conn.fetchval(
        "SELECT count(*) FROM event_articles WHERE event_id = $1", event_id
    )
    return count or 0


async def _get_event_outlet_count(conn: asyncpg.Connection, event_id: str) -> int:
    """Number of distinct outlets covering an event."""
    count = await conn.fetchval(
        """
        SELECT count(DISTINCT a.outlet_id)
        FROM event_articles ea
        JOIN articles a ON a.id = ea.article_id
        WHERE ea.event_id = $1
        """,
        event_id,
    )
    return count or 0


async def _get_lusa_metrics(conn: asyncpg.Connection, event_id: str) -> dict[str, int]:
    """Count lusa_cited and lusa_likely articles in an event."""
    row = await conn.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE a.lusa_cited) AS lusa_cited_count,
            count(*) FILTER (WHERE a.lusa_likely) AS lusa_likely_count,
            count(*) AS total
        FROM event_articles ea
        JOIN articles a ON a.id = ea.article_id
        WHERE ea.event_id = $1
        """,
        event_id,
    )
    if not row:
        return {"lusa_cited_count": 0, "lusa_likely_count": 0, "total": 0}
    return {
        "lusa_cited_count": row["lusa_cited_count"] or 0,
        "lusa_likely_count": row["lusa_likely_count"] or 0,
        "total": row["total"] or 1,  # avoid division by zero
    }


async def _get_frame_labels(
    conn: asyncpg.Connection, event_id: str
) -> list[str]:
    """Get all frame_labels across an event's articles."""
    rows = await conn.fetch(
        """
        SELECT jsonb_array_elements_text(aa.frame_labels) AS label
        FROM article_analysis aa
        JOIN event_articles ea ON ea.article_id = aa.article_id
        WHERE ea.event_id = $1
        """,
        event_id,
    )
    return [r["label"] for r in rows]


async def _get_document_count(conn: asyncpg.Connection, event_id: str) -> int:
    """Number of linked source documents."""
    count = await conn.fetchval(
        "SELECT count(*) FROM event_documents WHERE event_id = $1", event_id
    )
    return count or 0


async def _get_articles_citing_documents(
    conn: asyncpg.Connection, event_id: str
) -> int:
    """Number of articles that cite documents."""
    count = await conn.fetchval(
        """
        SELECT count(*) FROM article_analysis aa
        JOIN event_articles ea ON ea.article_id = aa.article_id
        WHERE ea.event_id = $1 AND aa.cites_document = TRUE
        """,
        event_id,
    )
    return count or 0


async def _get_silent_outlets(
    conn: asyncpg.Connection, event_id: str
) -> list[str]:
    """List of active outlet slugs that did NOT cover this event."""
    rows = await conn.fetch(
        """
        SELECT o.slug FROM outlets o
        WHERE o.active = TRUE
          AND o.id NOT IN (
            SELECT DISTINCT a.outlet_id
            FROM event_articles ea
            JOIN articles a ON a.id = ea.article_id
            WHERE ea.event_id = $1
          )
        ORDER BY o.slug
        """,
        event_id,
    )
    return [r["slug"] for r in rows]


async def _get_covering_outlet_slugs(
    conn: asyncpg.Connection, event_id: str
) -> list[str]:
    """List of outlet slugs that covered this event."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT o.slug
        FROM outlets o
        JOIN articles a ON a.outlet_id = o.id
        JOIN event_articles ea ON ea.article_id = a.id
        WHERE ea.event_id = $1
        ORDER BY o.slug
        """,
        event_id,
    )
    return [r["slug"] for r in rows]


def _compute_framing_divergence(frame_labels: list[str]) -> float:
    """Simple framing divergence: 1 - (dominant_frame_ratio).

    Returns 0.0 if all articles use the same frame, approaching 1.0
    if frames are evenly distributed.
    """
    if not frame_labels:
        return 0.0

    from collections import Counter
    counts = Counter(frame_labels)
    total = len(frame_labels)
    most_common_count = counts.most_common(1)[0][1] if counts else 0
    dominant_ratio = most_common_count / total if total > 0 else 0
    return round(1.0 - dominant_ratio, 4)


def _compute_undercoverage_score(
    coverage_breadth: float,
    evidence_density: float,
    lusa_dependency: float,
) -> float:
    """Composite undercoverage signal.

    High undercoverage = low coverage + institutional backing but few covering.
    Weight: 60% inverse coverage, 25% evidence gap, 15% Lusa dependency.
    """
    coverage_gap = 1.0 - coverage_breadth
    evidence_gap = max(0.0, 0.5 - evidence_density)
    weighted = (0.6 * coverage_gap) + (0.25 * evidence_gap) + (0.15 * lusa_dependency)
    return round(min(1.0, max(0.0, weighted)), 4)


# ──────────────────────────────────────────────────────────────────────────────
# Storage helpers
# ──────────────────────────────────────────────────────────────────────────────


async def _store_event_scores(
    conn: asyncpg.Connection,
    event_id: str,
    scores: dict[str, Any],
) -> None:
    """Store or update the event_scores row."""
    await conn.execute(
        """
        INSERT INTO event_scores (
            event_id, coverage_breadth, framing_divergence, evidence_density,
            lusa_dependency, undercoverage_score, explanation
        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (event_id) DO UPDATE
        SET coverage_breadth = $2, framing_divergence = $3, evidence_density = $4,
            lusa_dependency = $5, undercoverage_score = $6, explanation = $7,
            computed_at = now()
        """,
        event_id,
        scores["coverage_breadth"],
        scores["framing_divergence"],
        scores["evidence_density"],
        scores["lusa_dependency"],
        scores["undercoverage_score"],
        scores["explanation"],
    )


async def _create_undercoverage_flag(
    conn: asyncpg.Connection,
    event_id: str,
    flag_type: str,
    reason: str,
    silent_outlets: list[str],
    linked_document_id: str | None = None,
) -> None:
    """Create an undercoverage flag. Idempotent by flag_type per event."""
    import json as _json
    # Delete existing same-type flag for this event (idempotent re-run)
    await conn.execute(
        "DELETE FROM undercoverage_flags WHERE event_id = $1 AND flag_type = $2",
        event_id, flag_type,
    )
    await conn.execute(
        """
        INSERT INTO undercoverage_flags (
            event_id, reason, flag_type, silent_outlets, linked_document_id
        ) VALUES ($1, $2, $3, $4::jsonb, $5)
        """,
        event_id,
        reason,
        flag_type,
        _json.dumps(silent_outlets),
        linked_document_id,
    )


async def _promote_event_to_unreviewed(
    conn: asyncpg.Connection, event_id: str
) -> None:
    """Promote candidate events to 'unreviewed' after scoring."""
    await conn.execute(
        """
        UPDATE events SET status = 'unreviewed', updated_at = now()
        WHERE id = $1 AND status = 'candidate'
        """,
        event_id,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


async def score_batch(
    db_url: str | None = None,
    *,
    batch_size: int | None = None,
) -> dict[str, Any]:
    """Score a batch of events that have been enriched but not yet scored.

    Args:
        db_url: Postgres connection string. Reads from DATABASE_URL env if None.
        batch_size: Max events per run. Defaults to 50.

    Returns:
        Summary dict: {processed, scored, flags_created, errors}.
    """
    import os

    if db_url is None:
        db_url = os.getenv("DATABASE_URL", "")

    if batch_size is None:
        batch_size = int(os.getenv("SCORING_BATCH_SIZE", "50"))

    summary: dict[str, Any] = {
        "processed": 0,
        "scored": 0,
        "flags_created": 0,
        "promoted": 0,
        "errors": [],
    }

    total_outlets = 20  # fallback, updated below

    async with asyncpg.create_pool(db_url, min_size=1, max_size=3) as pool:
        async with pool.acquire() as conn:
            total_outlets = await _get_total_active_outlets(conn)

            # Find events with enrichment but no scores
            rows = await conn.fetch(
                """
                SELECT e.id::text, e.canonical_title, e.status,
                       ed_count.count AS doc_count
                FROM events e
                LEFT JOIN event_scores es ON es.event_id = e.id
                LEFT JOIN LATERAL (
                    SELECT count(*) AS count FROM event_documents ed2
                    WHERE ed2.event_id = e.id
                ) ed_count ON TRUE
                WHERE e.status IN ('candidate', 'unreviewed')
                  AND es.id IS NULL
                ORDER BY e.created_at
                LIMIT $1
                FOR UPDATE OF e SKIP LOCKED
                """,
                batch_size,
            )

            if not rows:
                logger.info("No events need scoring.")
                return summary

            logger.info("Scoring %d events...", len(rows))
            summary["processed"] = len(rows)

            for row in rows:
                try:
                    event_id = row["id"]
                    article_count = await _get_event_article_count(conn, event_id)
                    outlet_count = await _get_event_outlet_count(conn, event_id)

                    # Score dimensions
                    coverage_breadth = round(
                        outlet_count / max(total_outlets, 1), 4
                    )

                    frame_labels = await _get_frame_labels(conn, event_id)
                    framing_divergence = _compute_framing_divergence(frame_labels)

                    docs_citing = await _get_articles_citing_documents(conn, event_id)
                    total_articles = max(article_count, 1)
                    evidence_density = round(docs_citing / total_articles, 4)

                    lusa_metrics = await _get_lusa_metrics(conn, event_id)
                    lusa_dependency = round(
                        (lusa_metrics["lusa_cited_count"]
                         + lusa_metrics["lusa_likely_count"])
                        / lusa_metrics["total"],
                        4,
                    )

                    undercoverage_score = _compute_undercoverage_score(
                        coverage_breadth, evidence_density, lusa_dependency
                    )

                    explanation = (
                        f"coverage={coverage_breadth:.2f} "
                        f"({outlet_count}/{total_outlets} outlets), "
                        f"framing_div={framing_divergence:.2f} "
                        f"({len(set(frame_labels))} unique frames), "
                        f"evidence={evidence_density:.2f}, "
                        f"lusa_dep={lusa_dependency:.2f}"
                    )

                    scores = {
                        "coverage_breadth": coverage_breadth,
                        "framing_divergence": framing_divergence,
                        "evidence_density": evidence_density,
                        "lusa_dependency": lusa_dependency,
                        "undercoverage_score": undercoverage_score,
                        "explanation": explanation,
                    }

                    await _store_event_scores(conn, event_id, scores)
                    summary["scored"] += 1

                    # Undercoverage flagging
                    silent_outlets = await _get_silent_outlets(conn, event_id)

                    if coverage_breadth < 0.15 and article_count >= 3:
                        await _create_undercoverage_flag(
                            conn, event_id, "low_breadth",
                            f"Only {outlet_count}/{total_outlets} outlets covered "
                            f"({coverage_breadth:.0%}), {article_count} articles",
                            silent_outlets,
                        )
                        summary["flags_created"] += 1

                    if lusa_dependency > 0.4 and len(silent_outlets) > 8:
                        cover_slugs = await _get_covering_outlet_slugs(conn, event_id)
                        await _create_undercoverage_flag(
                            conn, event_id, "lusa_silent",
                            f"High Lusa dependency ({lusa_dependency:.0%}) with "
                            f"{len(silent_outlets)} silent outlets",
                            silent_outlets,
                        )
                        summary["flags_created"] += 1

                    # Promote candidate → unreviewed
                    if row["status"] == "candidate":
                        await _promote_event_to_unreviewed(conn, event_id)
                        summary["promoted"] += 1

                    logger.debug(
                        "  ✓ %s: breadth=%.2f div=%.2f ev=%.2f lusa=%.2f ucov=%.2f",
                        row["canonical_title"][:50],
                        coverage_breadth,
                        framing_divergence,
                        evidence_density,
                        lusa_dependency,
                        undercoverage_score,
                    )
                except Exception as exc:
                    summary["errors"].append(
                        {"event_id": row["id"], "error": str(exc)}
                    )
                    logger.error("Error scoring event %s: %s", row["id"], exc)

    logger.info(
        "Scoring complete: %d scored, %d flags, %d promoted to unreviewed",
        summary["scored"],
        summary["flags_created"],
        summary["promoted"],
    )

    return summary