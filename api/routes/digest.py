"""pt-media-os — Digest API Routes"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter
from db.pool import fetch_one

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/digest/today")
async def get_today_digest():
    """Get today's daily digest."""
    today = date.today()
    row = await fetch_one(
        "SELECT * FROM daily_digests WHERE digest_date = $1",
        today,
    )
    if not row:
        return {"digest_date": str(today), "top_events": [], "undercovered": [], "metadata": {}}
    return {
        "digest_date": str(row["digest_date"]),
        "top_events": row["top_events"],
        "undercovered": row["undercovered"],
        "metadata": row["metadata"],
    }


@router.get("/digest/{digest_date}")
async def get_digest(digest_date: date):
    """Get a specific date's digest."""
    row = await fetch_one(
        "SELECT * FROM daily_digests WHERE digest_date = $1",
        digest_date,
    )
    if not row:
        return {"error": "Digest not found"}, 404
    return {
        "digest_date": str(row["digest_date"]),
        "top_events": row["top_events"],
        "undercovered": row["undercovered"],
        "metadata": row["metadata"],
    }
