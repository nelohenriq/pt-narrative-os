"""pt-media-os — Undercoverage API Routes"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from db.pool import fetch_all

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/events/undercovered")
async def list_undercovered():
    """List published undercoverage flags for published events."""
    rows = await fetch_all(
        """SELECT uf.id, uf.event_id, uf.reason, uf.flag_type, uf.silent_outlets,
                  e.canonical_title, es.coverage_breadth, es.undercoverage_score
           FROM undercoverage_flags uf
           JOIN events e ON uf.event_id = e.id
           LEFT JOIN event_scores es ON e.id = es.event_id
           WHERE e.is_published = TRUE AND uf.is_published = TRUE
           ORDER BY es.undercoverage_score DESC NULLS LAST"""
    )
    return [
        {
            "id": str(r["id"]),
            "event_id": str(r["event_id"]),
            "event_title": r["canonical_title"],
            "reason": r["reason"],
            "flag_type": r["flag_type"],
            "silent_outlets": r["silent_outlets"],
            "coverage_breadth": float(r["coverage_breadth"]) if r["coverage_breadth"] else None,
            "undercoverage_score": float(r["undercoverage_score"]) if r["undercoverage_score"] else None,
        }
        for r in rows
    ]
