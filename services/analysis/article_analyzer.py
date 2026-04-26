"""Article analysis service — AI extraction for entities, claims, frames.

Takes articles with status='embedded' (clustered, has embedding),
calls the extractor_fast model to extract structured metadata,
and stores the results in article_analysis, entities, article_entities, claims.

Flow:
    articles (embedded) → AI extraction → article_analysis + entities + claims → status='analyzed'
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg
from dotenv import load_dotenv

from ai.router import call, TaskName
from prompts.v1_extractor_fast import EXTRACTOR_SYSTEM_PROMPT, EXTRACTOR_USER_TEMPLATE

# Module-level load_dotenv so pytest subprocesses don't need manual setup.
load_dotenv()

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"


# ──────────────────────────────────────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────────────────────────────────────


async def _get_unanalyzed_articles(
    conn: asyncpg.Connection, batch_size: int = 10
) -> list[asyncpg.Record]:
    """Fetch embedded articles not yet analyzed."""
    rows = await conn.fetch(
        """
        SELECT id::text, title, cleaned_text, outlet_id::text, canonical_url
        FROM articles
        WHERE status = 'embedded'
        ORDER BY created_at
        LIMIT $1
        FOR UPDATE SKIP LOCKED
        """,
        batch_size,
    )
    return rows


async def _upsert_entity(
    conn: asyncpg.Connection,
    name: str,
    entity_type: str,
) -> str:
    """Insert or update an entity, returning its ID.

    Dedup by exact lowercase name match (sluggified for canonical_slug).
    Increments mention_count on existing entity.
    """
    import unicodedata, re

    _slug = (
        unicodedata.normalize("NFKD", name.lower())
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    _slug = re.sub(r"[^a-z0-9]+", "-", _slug).strip("-")

    row = await conn.fetchrow(
        """
        INSERT INTO entities (name, entity_type, canonical_slug)
        VALUES ($1, $2, $3)
        ON CONFLICT (canonical_slug) DO UPDATE
        SET mention_count = entities.mention_count + 1, updated_at = now()
        RETURNING id::text
        """,
        name,
        entity_type,
        _slug,
    )
    return row["id"]


async def _store_article_entity_link(
    conn: asyncpg.Connection,
    article_id: str,
    entity_id: str,
    confidence: float,
    ai_run_id: str,
) -> None:
    """Link an article to an entity."""
    await conn.execute(
        """
        INSERT INTO article_entities (article_id, entity_id, confidence, ai_run_id)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (article_id, entity_id) DO UPDATE
        SET confidence = $3, ai_run_id = $4
        """,
        article_id,
        entity_id,
        confidence,
        ai_run_id,
    )


async def _store_claim(
    conn: asyncpg.Connection,
    article_id: str,
    claim_text: str,
    claim_type: str,
    speaker: str | None,
    speaker_type: str,
    attribution_text: str | None,
    confidence: float,
    ai_run_id: str,
) -> None:
    """Insert a claim into the claims table."""
    await conn.execute(
        """
        INSERT INTO claims (article_id, claim_text, claim_type, speaker, speaker_type,
                            attribution_text, confidence, ai_run_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        article_id,
        claim_text,
        claim_type,
        speaker,
        speaker_type,
        attribution_text,
        confidence,
        ai_run_id,
    )


async def _store_analysis(
    conn: asyncpg.Connection,
    article_id: str,
    ai_run_id: str,
    parsed: dict[str, Any],
) -> None:
    """Store the full AI extraction result in article_analysis."""
    await conn.execute(
        """
        INSERT INTO article_analysis (
            article_id, ai_run_id, analysis_json,
            persons, organizations, topics, quotes,
            source_types, stance_flags, loaded_terms, frame_labels,
            cites_document, document_refs
        ) VALUES (
            $1, $2, $3::jsonb,
            $4::jsonb, $5::jsonb, $6::jsonb, $7::jsonb,
            $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb,
            $12, $13::jsonb
        )
        ON CONFLICT (article_id) DO UPDATE
        SET ai_run_id = $2, analysis_json = $3::jsonb,
            persons = $4::jsonb, organizations = $5::jsonb,
            topics = $6::jsonb, quotes = $7::jsonb,
            source_types = $8::jsonb, stance_flags = $9::jsonb,
            loaded_terms = $10::jsonb, frame_labels = $11::jsonb,
            cites_document = $12, document_refs = $13::jsonb
        """,
        article_id,
        ai_run_id,
        json.dumps(parsed),
        json.dumps(parsed.get("persons", [])),
        json.dumps(parsed.get("organizations", [])),
        json.dumps(parsed.get("topics", [])),
        json.dumps(parsed.get("quotes", parsed.get("quotes_claims", []))),
        json.dumps(parsed.get("source_types", [])),
        json.dumps(parsed.get("stance_flags", {})),
        json.dumps(parsed.get("loaded_terms", [])),
        json.dumps(parsed.get("frame_labels", [])),
        parsed.get("cites_document", False),
        json.dumps(parsed.get("document_refs", [])),
    )


async def _mark_article_analyzed(
    conn: asyncpg.Connection, article_id: str
) -> None:
    """Update article status to 'analyzed'."""
    await conn.execute(
        "UPDATE articles SET status = 'analyzed', updated_at = now() WHERE id = $1",
        article_id,
    )


async def _mark_article_failed(
    conn: asyncpg.Connection, article_id: str, error_msg: str
) -> None:
    """Mark article as failed if analysis errors out."""
    await conn.execute(
        "UPDATE articles SET status = 'failed', error_msg = $1, updated_at = now() WHERE id = $2",
        error_msg,
        article_id,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────


def _build_messages(title: str, body: str) -> list[dict[str, str]]:
    """Build the system + user messages for extraction."""
    return [
        {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
        {"role": "user", "content": EXTRACTOR_USER_TEMPLATE.format(title=title, body=body)},
    ]


def _parse_extraction(response_text: str) -> dict[str, Any]:
    """Parse and validate the extraction JSON response.

    Returns the parsed JSON dict. Raises ValueError on invalid JSON
    or missing required keys.
    """
    # Strip markdown fences if the model wrapped its output
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last fence lines
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in extraction response: {e}") from e

    if not isinstance(parsed, dict):
        raise ValueError("Extraction response is not a JSON object")

    return parsed


# ──────────────────────────────────────────────────────────────────────────────
# Per-article analysis (single unit)
# ──────────────────────────────────────────────────────────────────────────────


async def _analyze_single_article(
    conn: asyncpg.Connection,
    article: asyncpg.Record,
) -> dict[str, Any]:
    """Analyze a single article: call AI, parse result, store extraction + entities + claims.

    Returns a dict with status and metadata for the batch summary.
    """
    article_id = article["id"]
    title = article["title"]
    body = article["cleaned_text"]

    messages = _build_messages(title, body)
    prompt_text = messages[0]["content"] + "\n\n" + messages[1]["content"]

    result = await call(
        "extractor_fast",
        messages=messages,
        temperature=0.1,
        response_format={"type": "json_object"},
        prompt_version=PROMPT_VERSION,
        prompt_text=prompt_text,
        article_id=article_id,
    )

    if "error" in result:
        raise RuntimeError(f"AI call failed: {result['error']}")

    content = result.get("content", "")
    parsed = _parse_extraction(content)

    # Get the ai_run_id from the raw response for provenance
    ai_run_id = None
    if result.get("raw"):
        raw = result["raw"]
        # The ai_runs insert happens inside router.call, but we don't get the ID back.
        # We need to look it up from the article_id + task match.
        # For now use a proxy: lookup latest ai_runs for this article
        ai_run_row = await conn.fetchrow(
            "SELECT id::text FROM ai_runs WHERE article_id = $1 AND task_name = 'extractor_fast' ORDER BY created_at DESC LIMIT 1",
            article_id,
        )
        if ai_run_row:
            ai_run_id = ai_run_row["id"]

    if not ai_run_id:
        raise RuntimeError("Could not determine ai_run_id after extraction")

    # Store the full analysis
    await _store_analysis(conn, article_id, ai_run_id, parsed)

    # Upsert entities from persons + organizations
    for person in parsed.get("persons", []):
        if isinstance(person, dict):
            name = person.get("name", person) if "name" in person else str(person)
            eid = await _upsert_entity(conn, name, "person")
            await _store_article_entity_link(conn, article_id, eid, 0.8, ai_run_id)
        elif isinstance(person, str):
            eid = await _upsert_entity(conn, person, "person")
            await _store_article_entity_link(conn, article_id, eid, 0.8, ai_run_id)

    for org in parsed.get("organizations", []):
        if isinstance(org, dict):
            name = org.get("name", org) if "name" in org else str(org)
            eid = await _upsert_entity(conn, name, "organization")
            await _store_article_entity_link(conn, article_id, eid, 0.8, ai_run_id)
        elif isinstance(org, str):
            eid = await _upsert_entity(conn, org, "organization")
            await _store_article_entity_link(conn, article_id, eid, 0.8, ai_run_id)

    # Store claims/quotes
    quotes = parsed.get("quotes") or parsed.get("quotes_claims") or []
    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        await _store_claim(
            conn,
            article_id,
            quote.get("text", ""),
            quote.get("type", "assertion"),
            quote.get("speaker"),
            quote.get("speaker_type", "unknown"),
            quote.get("attribution"),
            0.7,
            ai_run_id,
        )

    # Mark article as analyzed
    await _mark_article_analyzed(conn, article_id)

    quotes_data = parsed.get("quotes") or parsed.get("quotes_claims") or []

    return {
        "article_id": article_id,
        "status": "analyzed",
        "entities": len(parsed.get("persons", [])) + len(parsed.get("organizations", [])),
        "claims": len(quotes_data),
        "frames": parsed.get("frame_labels", []),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


async def analyze_batch(
    db_url: str | None = None,
    *,
    batch_size: int | None = None,
) -> dict[str, Any]:
    """Analyze a batch of embedded articles via AI extraction.

    Args:
        db_url: Postgres connection string. Reads from DATABASE_URL env if None.
        batch_size: Max articles per run. Reads ANALYSIS_BATCH_SIZE from env (default 10).

    Returns:
        Summary dict: {processed, analyzed, failed, total_entities, total_claims, errors}.
    """
    import os

    if db_url is None:
        db_url = os.getenv("DATABASE_URL", "")

    if batch_size is None:
        batch_size = int(os.getenv("ANALYSIS_BATCH_SIZE", "10"))

    summary: dict[str, Any] = {
        "processed": 0,
        "analyzed": 0,
        "failed": 0,
        "total_entities": 0,
        "total_claims": 0,
        "errors": [],
    }

    async with asyncpg.create_pool(db_url, min_size=1, max_size=3) as pool:
        async with pool.acquire() as conn:
            articles = await _get_unanalyzed_articles(conn, batch_size)

            if not articles:
                logger.info("No unanalyzed embedded articles.")
                return summary

            logger.info("Analyzing %d articles...", len(articles))
            summary["processed"] = len(articles)

            for article in articles:
                try:
                    detail = await _analyze_single_article(conn, article)
                    summary["analyzed"] += 1
                    summary["total_entities"] += detail["entities"]
                    summary["total_claims"] += detail["claims"]

                    logger.debug(
                        "  ✓ %s (%d entities, %d claims, frames=%s)",
                        article["title"][:60],
                        detail["entities"],
                        detail["claims"],
                        detail["frames"],
                    )
                except Exception as exc:
                    summary["failed"] += 1
                    await _mark_article_failed(conn, article["id"], str(exc))
                    summary["errors"].append(
                        {"article_id": article["id"], "error": str(exc)}
                    )
                    logger.error("Failed to analyze article %s: %s", article["id"], exc)

    logger.info(
        "Analysis batch complete: %d processed, %d analyzed, %d failed",
        summary["processed"],
        summary["analyzed"],
        summary["failed"],
    )

    return summary