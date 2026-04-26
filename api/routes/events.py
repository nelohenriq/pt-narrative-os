"""
pt-media-os — Events API Routes
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from db.pool import fetch_all, fetch_one

logger = logging.getLogger(__name__)
router = APIRouter()


class EventListItem(BaseModel):
    id: str
    canonical_title: str
    article_count: int
    outlet_count: int
    coverage_breadth: float | None
    framing_divergence: float | None
    undercoverage_score: float | None
    status: str
    first_seen_at: str | None
    reviewed_at: str | None


class EventDetail(BaseModel):
    id: str
    canonical_title: str
    article_count: int
    outlet_count: int
    status: str
    first_seen_at: str | None
    last_seen_at: str | None
    scores: dict | None
    summaries: list[dict]
    articles: list[dict]
    documents: list[dict]


@router.get("/events")
async def list_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    outlet: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """List published events with pagination and optional filters."""
    offset = (page - 1) * page_size

    where_clauses = ["e.is_published = TRUE"]
    params = []
    param_idx = 1

    if outlet:
        where_clauses.append(
            f"EXISTS (SELECT 1 FROM event_articles ea JOIN articles a ON ea.article_id = a.id JOIN outlets o ON a.outlet_id = o.id WHERE ea.event_id = e.id AND o.slug = ${param_idx})"
        )
        params.append(outlet)
        param_idx += 1

    if date_from:
        where_clauses.append(f"e.first_seen_at >= ${param_idx}::timestamptz")
        params.append(date_from)
        param_idx += 1

    if date_to:
        where_clauses.append(f"e.first_seen_at <= ${param_idx}::timestamptz")
        params.append(date_to)
        param_idx += 1

    where = " AND ".join(where_clauses)

    rows = await fetch_all(
        f"""SELECT e.id, e.canonical_title, e.article_count, e.outlet_count,
                   e.status, e.first_seen_at, e.reviewed_at,
                   es.coverage_breadth, es.framing_divergence, es.undercoverage_score
            FROM events e
            LEFT JOIN event_scores es ON e.id = es.event_id
            WHERE {where}
            ORDER BY e.first_seen_at DESC
            LIMIT {page_size} OFFSET {offset}""",
        *params,
    )

    total_row = await fetch_one(
        f"SELECT count(*) as cnt FROM events e WHERE {where}",
        *params,
    )
    total = total_row["cnt"] if total_row else 0

    items = []
    for r in rows:
        items.append({
            "id": str(r["id"]),
            "canonical_title": r["canonical_title"],
            "article_count": r["article_count"],
            "outlet_count": r["outlet_count"],
            "coverage_breadth": float(r["coverage_breadth"]) if r["coverage_breadth"] else None,
            "framing_divergence": float(r["framing_divergence"]) if r["framing_divergence"] else None,
            "undercoverage_score": float(r["undercoverage_score"]) if r["undercoverage_score"] else None,
            "status": r["status"],
            "first_seen_at": str(r["first_seen_at"]) if r["first_seen_at"] else None,
            "reviewed_at": str(r["reviewed_at"]) if r["reviewed_at"] else None,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/events/{event_id}")
async def get_event(event_id: UUID):
    """Get full event detail with articles, scores, summaries, and documents."""
    event = await fetch_one(
        """SELECT e.*, es.coverage_breadth, es.framing_divergence,
                  es.evidence_density, es.lusa_dependency, es.undercoverage_score,
                  es.explanation
           FROM events e
           LEFT JOIN event_scores es ON e.id = es.event_id
           WHERE e.id = $1""",
        str(event_id),
    )

    if not event:
        return {"error": "Event not found"}, 404

    # Get articles
    articles = await fetch_all(
        """SELECT a.id, a.title, a.canonical_url, a.published_at, a.word_count,
                  a.lusa_cited, a.lusa_likely, o.name as outlet_name, o.slug as outlet_slug
           FROM articles a
           JOIN outlets o ON a.outlet_id = o.id
           JOIN event_articles ea ON a.id = ea.article_id
           WHERE ea.event_id = $1
           ORDER BY a.published_at ASC""",
        str(event_id),
    )

    # Get summaries
    summaries = await fetch_all(
        """SELECT summary_type, content, model_name, prompt_version, ai_run_id
           FROM event_summaries WHERE event_id = $1""",
        str(event_id),
    )

    # Get documents
    documents = await fetch_all(
        """SELECT sd.id, sd.title, sd.source_type, sd.canonical_url, ed.matched_by
           FROM source_documents sd
           JOIN event_documents ed ON sd.id = ed.document_id
           WHERE ed.event_id = $1""",
        str(event_id),
    )

    scores = None
    if event["coverage_breadth"] is not None:
        scores = {
            "coverage_breadth": float(event["coverage_breadth"]),
            "framing_divergence": float(event["framing_divergence"]) if event["framing_divergence"] else None,
            "evidence_density": float(event["evidence_density"]) if event["evidence_density"] else None,
            "lusa_dependency": float(event["lusa_dependency"]) if event["lusa_dependency"] else None,
            "undercoverage_score": float(event["undercoverage_score"]) if event["undercoverage_score"] else None,
            "explanation": event["explanation"],
        }

    return {
        "id": str(event["id"]),
        "canonical_title": event["canonical_title"],
        "article_count": event["article_count"],
        "outlet_count": event["outlet_count"],
        "status": event["status"],
        "is_published": event["is_published"],
        "first_seen_at": str(event["first_seen_at"]) if event["first_seen_at"] else None,
        "last_seen_at": str(event["last_seen_at"]) if event["last_seen_at"] else None,
        "scores": scores,
        "summaries": [
            {
                "type": str(s["summary_type"]),
                "content": s["content"],
                "model": s["model_name"],
                "prompt_version": s["prompt_version"],
                "ai_run_id": str(s["ai_run_id"]),
            }
            for s in summaries
        ],
        "articles": [
            {
                "id": str(a["id"]),
                "title": a["title"],
                "url": a["canonical_url"],
                "outlet": a["outlet_name"],
                "outlet_slug": a["outlet_slug"],
                "published_at": str(a["published_at"]) if a["published_at"] else None,
                "word_count": a["word_count"],
                "lusa_cited": a["lusa_cited"],
                "lusa_likely": a["lusa_likely"],
            }
            for a in articles
        ],
        "documents": [
            {
                "id": str(d["id"]),
                "title": d["title"],
                "source_type": str(d["source_type"]),
                "url": d["canonical_url"],
                "matched_by": d["matched_by"],
            }
            for d in documents
        ],
    }


@router.get("/events/{event_id}/provenance")
async def get_event_provenance(event_id: UUID):
    """Trace AI outputs back to ai_runs and source articles."""
    ai_runs = await fetch_all(
        """SELECT ar.id, ar.task_name, ar.provider, ar.model_name, ar.prompt_version,
                  ar.latency_ms, ar.input_token_count, ar.output_token_count,
                  ar.status, ar.temperature, ar.created_at
           FROM ai_runs ar
           WHERE ar.event_id = $1
           ORDER BY ar.created_at DESC""",
        str(event_id),
    )

    article_runs = await fetch_all(
        """SELECT ar.id, ar.task_name, ar.provider, ar.model_name, ar.prompt_version,
                  ar.latency_ms, ar.status, ar.article_id, a.title as article_title
           FROM ai_runs ar
           JOIN articles a ON ar.article_id = a.id
           JOIN event_articles ea ON a.id = ea.article_id
           WHERE ea.event_id = $1
           ORDER BY ar.created_at DESC""",
        str(event_id),
    )

    return {
        "event_id": str(event_id),
        "event_level_runs": [
            {
                "id": str(r["id"]),
                "task": r["task_name"],
                "provider": r["provider"],
                "model": r["model_name"],
                "prompt_version": r["prompt_version"],
                "latency_ms": r["latency_ms"],
                "input_tokens": r["input_token_count"],
                "output_tokens": r["output_token_count"],
                "status": str(r["status"]),
                "created_at": str(r["created_at"]),
            }
            for r in ai_runs
        ],
        "article_level_runs": [
            {
                "id": str(r["id"]),
                "task": r["task_name"],
                "provider": r["provider"],
                "model": r["model_name"],
                "article_id": str(r["article_id"]),
                "article_title": r["article_title"],
                "latency_ms": r["latency_ms"],
                "status": str(r["status"]),
            }
            for r in article_runs
        ],
    }
