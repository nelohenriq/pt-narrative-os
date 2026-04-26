"""pt-media-os — Search API Routes"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from db.pool import fetch_all

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/search")
async def search(q: str = Query(..., min_length=2)):
    """Full-text search across events and articles."""
    # Search events by title
    events = await fetch_all(
        """SELECT e.id, e.canonical_title, e.article_count, e.outlet_count,
                  e.first_seen_at, es.coverage_breadth
           FROM events e
           LEFT JOIN event_scores es ON e.id = es.event_id
           WHERE e.is_published = TRUE
             AND (to_tsvector('portuguese', e.canonical_title) @@ plainto_tsquery('portuguese', $1)
                  OR e.canonical_title ILIKE '%' || $1 || '%')
           ORDER BY e.first_seen_at DESC
           LIMIT 20""",
        q,
    )

    # Search articles by title
    articles = await fetch_all(
        """SELECT a.id, a.title, a.canonical_url, a.published_at, o.name as outlet_name
           FROM articles a
           JOIN outlets o ON a.outlet_id = o.id
           WHERE (to_tsvector('portuguese', a.title) @@ plainto_tsquery('portuguese', $1)
                  OR a.title ILIKE '%' || $1 || '%')
           ORDER BY a.published_at DESC
           LIMIT 20""",
        q,
    )

    return {
        "query": q,
        "events": [
            {
                "id": str(e["id"]),
                "title": e["canonical_title"],
                "article_count": e["article_count"],
                "outlet_count": e["outlet_count"],
                "first_seen_at": str(e["first_seen_at"]) if e["first_seen_at"] else None,
                "coverage_breadth": float(e["coverage_breadth"]) if e["coverage_breadth"] else None,
            }
            for e in events
        ],
        "articles": [
            {
                "id": str(a["id"]),
                "title": a["title"],
                "url": a["canonical_url"],
                "outlet": a["outlet_name"],
                "published_at": str(a["published_at"]) if a["published_at"] else None,
            }
            for a in articles
        ],
    }
