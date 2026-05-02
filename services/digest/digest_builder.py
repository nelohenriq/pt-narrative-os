"""
pt-media-os — Digest Builder Service

Builds the daily homepage feed from published events.

Trigger: cron daily at 07:00 UTC (08:00 Lisbon time)
Input: published events from last 24 hours
Output: row in daily_digests
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta

from db.pool import fetch_all, fetch_one

logger = logging.getLogger(__name__)


async def build_daily_digest(target_date: date | None = None) -> str | None:
    """
    Build the daily digest for a specific date.
    Returns the digest ID or None if no events.
    """
    target_date = target_date or date.today()
    since = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC) - timedelta(hours=24)

    # Get published events from the last 24 hours
    events = await fetch_all(
        """SELECT e.id, e.canonical_title, e.article_count, e.outlet_count,
                  es.coverage_breadth, es.framing_divergence, es.evidence_density,
                  es.undercoverage_score
           FROM events e
           LEFT JOIN event_scores es ON e.id = es.event_id
           WHERE e.is_published = TRUE
             AND e.reviewed_at >= $1
           ORDER BY es.coverage_breadth DESC NULLS LAST, es.framing_divergence DESC NULLS LAST""",
        since,
    )

    if not events:
        logger.info("No published events for digest on %s", target_date)
        return None

    # Build top events list (sorted by coverage breadth, then framing divergence)
    top_events = []
    for event in events[:20]:  # cap at 20 events
        top_events.append({
            "id": str(event["id"]),
            "title": event["canonical_title"],
            "article_count": event["article_count"],
            "outlet_count": event["outlet_count"],
            "coverage_breadth": float(event["coverage_breadth"]) if event["coverage_breadth"] else None,
            "framing_divergence": float(event["framing_divergence"]) if event["framing_divergence"] else None,
        })

    # Get published undercoverage flags for these events
    event_ids = [str(e["id"]) for e in events]
    undercovered = []
    if event_ids:
        placeholders = ", ".join(f"${i+1}" for i in range(len(event_ids)))
        flags = await fetch_all(
            f"""SELECT uf.event_id AS flag_event_id, uf.reason, uf.flag_type, uf.silent_outlets
                FROM undercoverage_flags uf
                INNER JOIN events e ON uf.event_id = e.id
                WHERE e.is_published = TRUE
                  AND uf.event_id IN ({placeholders})
                  AND uf.is_published = TRUE""",
            *event_ids,
        )
        for flag_row in flags:
            undercovered.append({
                "event_id": str(flag_row["flag_event_id"]),
                "reason": flag_row["reason"],
                "flag_type": flag_row["flag_type"],
                "silent_outlets": (
                    json.loads(flag_row["silent_outlets"])
                    if flag_row["silent_outlets"]
                    else []
                ),
            })

    # Build metadata
    metadata = {
        "total_events": len(events),
        "total_undercovered": len(undercovered),
        "generated_at": datetime.now(UTC).isoformat(),
    }

    # Insert into daily_digests
    row = await fetch_one(
        """INSERT INTO daily_digests (digest_date, top_events, undercovered, metadata)
           VALUES ($1, $2::jsonb, $3::jsonb, $4::jsonb)
           ON CONFLICT (digest_date) DO UPDATE SET
               top_events = $2::jsonb, undercovered = $3::jsonb, metadata = $4::jsonb
           RETURNING id""",
        target_date,
        json.dumps(top_events),
        json.dumps(undercovered),
        json.dumps(metadata),
    )

    digest_id = str(row["id"]) if row else None
    logger.info(
        "Daily digest for %s: %d events, %d undercovered flags",
        target_date,
        len(events),
        len(undercovered),
    )
    return digest_id


async def run_digest_builder() -> str | None:
    """Build today's daily digest."""
    return await build_daily_digest()