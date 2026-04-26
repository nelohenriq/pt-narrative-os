"""pt-media-os — Outlets API Routes"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from db.pool import fetch_all, fetch_one

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/outlets")
async def list_outlets():
    """List all active outlets."""
    rows = await fetch_all(
        """SELECT id, name, slug, outlet_type, website_url, feed_url, erc_reference
           FROM outlets WHERE active = TRUE ORDER BY name"""
    )
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "slug": r["slug"],
            "type": str(r["outlet_type"]),
            "website_url": r["website_url"],
            "feed_url": r["feed_url"],
            "erc_reference": r["erc_reference"],
        }
        for r in rows
    ]


@router.get("/outlets/{slug}")
async def get_outlet(slug: str):
    """Get outlet profile with ownership and recent events."""
    outlet = await fetch_one(
        "SELECT * FROM outlets WHERE slug = $1 AND active = TRUE",
        slug,
    )
    if not outlet:
        return {"error": "Outlet not found"}, 404

    # Get ownership
    ownership = await fetch_all(
        """SELECT o.name, o.slug, o.owner_type, oo.stake_pct, oo.confidence, oo.source
           FROM owners o
           JOIN outlet_ownership oo ON o.id = oo.owner_id
           WHERE oo.outlet_id = $1""",
        str(outlet["id"]),
    )

    # Get recent events this outlet covered
    events = await fetch_all(
        """SELECT e.id, e.canonical_title, e.article_count, e.outlet_count,
                  e.first_seen_at, es.coverage_breadth, es.framing_divergence
           FROM events e
           JOIN event_articles ea ON e.id = ea.event_id
           JOIN articles a ON ea.article_id = a.id
           LEFT JOIN event_scores es ON e.id = es.event_id
           WHERE a.outlet_id = $1 AND e.is_published = TRUE
           ORDER BY e.first_seen_at DESC
           LIMIT 20""",
        str(outlet["id"]),
    )

    return {
        "id": str(outlet["id"]),
        "name": outlet["name"],
        "slug": outlet["slug"],
        "type": str(outlet["outlet_type"]),
        "website_url": outlet["website_url"],
        "erc_reference": outlet["erc_reference"],
        "ownership": [
            {
                "owner_name": o["name"],
                "owner_slug": o["slug"],
                "owner_type": o["owner_type"],
                "stake_pct": float(o["stake_pct"]) if o["stake_pct"] else None,
                "confidence": float(o["confidence"]) if o["confidence"] else None,
                "source": o["source"],
            }
            for o in ownership
        ],
        "recent_events": [
            {
                "id": str(e["id"]),
                "title": e["canonical_title"],
                "article_count": e["article_count"],
                "outlet_count": e["outlet_count"],
                "first_seen_at": str(e["first_seen_at"]) if e["first_seen_at"] else None,
                "coverage_breadth": float(e["coverage_breadth"]) if e["coverage_breadth"] else None,
                "framing_divergence": float(e["framing_divergence"]) if e["framing_divergence"] else None,
            }
            for e in events
        ],
    }
