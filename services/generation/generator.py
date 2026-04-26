"""Generation service — AI-generated summaries, framing comparisons, undercoverage cards.

Takes events with status='unreviewed' that have scores, generates
user-facing content via the AI router, and stores in event_summaries.

Flow:
    events (unreviewed, scored) → AI generation → event_summaries
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg
from dotenv import load_dotenv

from ai.router import call
from prompts.v1_summary_fast import (
    SUMMARY_FAST_SYSTEM,
    SUMMARY_FAST_USER,
    SUMMARY_FAST_PROMPT_VERSION,
)
from prompts.v1_framing_analyst import (
    FRAMING_ANALYST_SYSTEM,
    FRAMING_ANALYST_USER,
    FRAMING_ANALYST_PROMPT_VERSION,
)
from prompts.v1_undercoverage_card import (
    UNDERCOVERAGE_CARD_SYSTEM,
    UNDERCOVERAGE_CARD_USER,
    UNDERCOVERAGE_CARD_PROMPT_VERSION,
)

load_dotenv()

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────────────────────────────────────


async def _get_events_ready_for_generation(
    conn: asyncpg.Connection, batch_size: int = 20
) -> list[asyncpg.Record]:
    """Fetch unreviewed events with scores that haven't had summaries generated."""
    rows = await conn.fetch(
        """
        SELECT e.id::text, e.canonical_title, e.article_count, e.outlet_count,
               es.coverage_breadth, es.framing_divergence, es.evidence_density,
               es.lusa_dependency, es.undercoverage_score
        FROM events e
        JOIN event_scores es ON es.event_id = e.id
        LEFT JOIN event_summaries esum ON esum.event_id = e.id
            AND esum.summary_type = 'event_summary'
        WHERE e.status = 'unreviewed'
          AND esum.id IS NULL
        ORDER BY e.article_count DESC
        LIMIT $1
        FOR UPDATE OF e SKIP LOCKED
        """,
        batch_size,
    )
    return rows


async def _get_event_outlets(
    conn: asyncpg.Connection, event_id: str
) -> list[str]:
    """Get comma-separated outlet names covering this event."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT o.name
        FROM outlets o
        JOIN articles a ON a.outlet_id = o.id
        JOIN event_articles ea ON ea.article_id = a.id
        WHERE ea.event_id = $1
        ORDER BY o.name
        """,
        event_id,
    )
    return [r["name"] for r in rows]


async def _get_article_excerpts(
    conn: asyncpg.Connection, event_id: str, max_excerpts: int = 5
) -> list[str]:
    """Get article title + first 300 chars of cleaned_text for this event."""
    rows = await conn.fetch(
        """
        SELECT a.title, a.cleaned_text
        FROM articles a
        JOIN event_articles ea ON ea.article_id = a.id
        WHERE ea.event_id = $1
        ORDER BY a.published_at DESC
        LIMIT $2
        """,
        event_id,
        max_excerpts,
    )
    excerpts: list[str] = []
    for row in rows:
        body = row["cleaned_text"] or ""
        excerpt = body[:300]
        excerpts.append(f"TÍTULO: {row['title']}\nEXCERTO: {excerpt}...")
    return excerpts


async def _get_outlet_excerpts_for_framing(
    conn: asyncpg.Connection, event_id: str, max_per_outlet: int = 2
) -> list[str]:
    """Get per-outlet article excerpts for framing comparison."""
    rows = await conn.fetch(
        """
        SELECT a.title, a.cleaned_text, o.name AS outlet_name, o.slug AS outlet_slug
        FROM articles a
        JOIN outlets o ON o.id = a.outlet_id
        JOIN event_articles ea ON ea.article_id = a.id
        WHERE ea.event_id = $1
        ORDER BY o.name, a.published_at DESC
        """,
        event_id,
    )
    from collections import defaultdict
    by_outlet: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        slug = row["outlet_slug"]
        if len(by_outlet[slug]) < max_per_outlet:
            body = row["cleaned_text"] or ""
            by_outlet[slug].append(
                f"{row['outlet_name']} ({slug}): {body[:300]}..."
            )

    result: list[str] = []
    for slug, texts in sorted(by_outlet.items()):
        result.extend(texts)
    return result


async def _get_linked_documents(
    conn: asyncpg.Connection, event_id: str
) -> list[str]:
    """Get titles of linked source documents."""
    rows = await conn.fetch(
        """
        SELECT sd.title, sd.source_type
        FROM source_documents sd
        JOIN event_documents ed ON ed.document_id = sd.id
        WHERE ed.event_id = $1
        """,
        event_id,
    )
    return [f"[{r['source_type']}] {r['title']}" for r in rows]


async def _has_undercoverage_flags(
    conn: asyncpg.Connection, event_id: str
) -> bool:
    """Check if event has any undercoverage flags."""
    exists = await conn.fetchval(
        "SELECT 1 FROM undercoverage_flags WHERE event_id = $1 LIMIT 1",
        event_id,
    )
    return bool(exists)


async def _get_undercoverage_flag_data(
    conn: asyncpg.Connection, event_id: str
) -> dict[str, Any] | None:
    """Get the first undercoverage flag data for this event."""
    row = await conn.fetchrow(
        """
        SELECT reason, flag_type, silent_outlets::text AS silent_outlets_str,
               linked_document_id
        FROM undercoverage_flags
        WHERE event_id = $1
        LIMIT 1
        """,
        event_id,
    )
    if not row:
        return None

    import json as _json
    silent = []
    if row["silent_outlets_str"]:
        try:
            silent = _json.loads(row["silent_outlets_str"])
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "reason": row["reason"],
        "flag_type": row["flag_type"],
        "silent_outlets": silent,
        "linked_document_id": row["linked_document_id"],
    }


async def _get_total_outlets(conn: asyncpg.Connection) -> int:
    """Total active outlets tracked."""
    count = await conn.fetchval("SELECT count(*) FROM outlets WHERE active = TRUE")
    return count or 20


async def _store_summary(
    conn: asyncpg.Connection,
    event_id: str,
    summary_type: str,
    content: str,
    ai_run_id: str | None,
    model_name: str,
    prompt_version: str,
) -> None:
    """Store a generated summary."""
    if ai_run_id is None:
        ai_run_id = "00000000-0000-0000-0000-000000000002"  # placeholder

    await conn.execute(
        """
        INSERT INTO event_summaries (
            event_id, summary_type, content, ai_run_id, model_name, prompt_version
        ) VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (event_id, summary_type) DO UPDATE
        SET content = $3, ai_run_id = $4, model_name = $5, prompt_version = $6
        """,
        event_id,
        summary_type,
        content,
        ai_run_id,
        model_name,
        prompt_version,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Generation helpers
# ──────────────────────────────────────────────────────────────────────────────


async def _generate_event_summary(
    event: asyncpg.Record,
    outlet_list: str,
    article_excerpts_text: str,
    document_excerpts_text: str,
) -> dict[str, Any]:
    """Generate a neutral 3-sentence event summary."""
    messages = [
        {"role": "system", "content": SUMMARY_FAST_SYSTEM},
        {
            "role": "user",
            "content": SUMMARY_FAST_USER.format(
                event_title=event["canonical_title"],
                article_count=event["article_count"],
                outlet_list=outlet_list,
                article_excerpts=article_excerpts_text,
                document_excerpts=document_excerpts_text,
            ),
        },
    ]
    prompt_text = messages[0]["content"] + "\n\n" + messages[1]["content"]

    result = await call(
        "summarize",
        messages=messages,
        temperature=0.3,
        response_format={"type": "json_object"},
        prompt_version=SUMMARY_FAST_PROMPT_VERSION,
        prompt_text=prompt_text,
        event_id=event["id"],
    )

    return result


async def _generate_framing_comparison(
    event: asyncpg.Record,
    outlet_excerpts_text: str,
) -> dict[str, Any]:
    """Generate a framing comparison across outlets."""
    messages = [
        {"role": "system", "content": FRAMING_ANALYST_SYSTEM},
        {
            "role": "user",
            "content": FRAMING_ANALYST_USER.format(
                event_title=event["canonical_title"],
                outlet_excerpts=outlet_excerpts_text,
            ),
        },
    ]
    prompt_text = messages[0]["content"] + "\n\n" + messages[1]["content"]

    result = await call(
        "framing_analyst",
        messages=messages,
        temperature=0.3,
        response_format={"type": "json_object"},
        prompt_version=FRAMING_ANALYST_PROMPT_VERSION,
        prompt_text=prompt_text,
        event_id=event["id"],
    )

    return result


async def _generate_undercoverage_card(
    event: asyncpg.Record,
    flag_data: dict[str, Any],
    covering_outlets: str,
    silent_outlets_text: str,
    document_text: str,
    total_outlets: int,
) -> dict[str, Any]:
    """Generate an undercoverage explanation card."""
    messages = [
        {"role": "system", "content": UNDERCOVERAGE_CARD_SYSTEM},
        {
            "role": "user",
            "content": UNDERCOVERAGE_CARD_USER.format(
                event_title=event["canonical_title"],
                flag_reason=flag_data["reason"],
                silent_outlets=silent_outlets_text,
                covering_outlets=covering_outlets,
                document_excerpt=document_text,
                total_outlets=total_outlets,
            ),
        },
    ]
    prompt_text = messages[0]["content"] + "\n\n" + messages[1]["content"]

    # Undercoverage card uses summarize task (NIM deepseek-r1, fallback Groq)
    result = await call(
        "summarize",
        messages=messages,
        temperature=0.3,
        response_format={"type": "json_object"},
        prompt_version=UNDERCOVERAGE_CARD_PROMPT_VERSION,
        prompt_text=prompt_text,
        event_id=event["id"],
    )

    return result


def _extract_json_text(ai_result: dict[str, Any]) -> str | None:
    """Extract the content text from an AI call result."""
    if "error" in ai_result:
        return None
    content = ai_result.get("content", "")
    if not content:
        return None

    import json as _json
    # Try parsing as JSON to validate, but return the raw text
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        parsed = _json.loads(text)
        # For summary: extract "summary" key
        if isinstance(parsed, dict):
            return parsed.get("summary", text)
        return text
    except _json.JSONDecodeError:
        return text


def _extract_framing_text(ai_result: dict[str, Any]) -> str | None:
    """Extract the framing comparison from an AI call result."""
    if "error" in ai_result:
        return None
    content = ai_result.get("content", "")
    if not content:
        return None

    import json as _json
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        parsed = _json.loads(text)
        if isinstance(parsed, dict):
            return parsed.get("framing_comparison", text)
        return text
    except _json.JSONDecodeError:
        return text


def _extract_undercoverage_text(ai_result: dict[str, Any]) -> str | None:
    """Extract the undercoverage explanation from an AI call result."""
    if "error" in ai_result:
        return None
    content = ai_result.get("content", "")
    if not content:
        return None

    import json as _json
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        parsed = _json.loads(text)
        if isinstance(parsed, dict):
            return parsed.get("undercoverage_explanation", text)
        return text
    except _json.JSONDecodeError:
        return text


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


async def generate_batch(
    db_url: str | None = None,
    *,
    batch_size: int | None = None,
) -> dict[str, Any]:
    """Generate AI summaries for a batch of unreviewed, scored events.

    Args:
        db_url: Postgres connection string. Reads from DATABASE_URL env if None.
        batch_size: Max events per run. Defaults to 3 (expensive AI calls).

    Returns:
        Summary dict: {processed, summaries_generated, framings_generated,
                       undercoverage_cards_generated, errors}.
    """
    import os

    if db_url is None:
        db_url = os.getenv("DATABASE_URL", "")

    if batch_size is None:
        batch_size = int(os.getenv("GENERATION_BATCH_SIZE", "3"))

    summary: dict[str, Any] = {
        "processed": 0,
        "summaries_generated": 0,
        "framings_generated": 0,
        "undercoverage_cards_generated": 0,
        "errors": [],
    }

    async with asyncpg.create_pool(db_url, min_size=1, max_size=3) as pool:
        async with pool.acquire() as conn:
            events = await _get_events_ready_for_generation(conn, batch_size)

            if not events:
                logger.info("No events need generation.")
                return summary

            logger.info("Generating content for %d events...", len(events))
            summary["processed"] = len(events)

            for event in events:
                try:
                    event_id = event["id"]

                    outlets = await _get_event_outlets(conn, event_id)
                    outlet_list = ", ".join(outlets) if outlets else "nenhum"

                    # ── Event summary ──
                    article_excerpts = await _get_article_excerpts(conn, event_id)
                    article_excerpts_text = "\n---\n".join(article_excerpts) if article_excerpts else "(sem artigos)"

                    docs = await _get_linked_documents(conn, event_id)
                    document_excerpts_text = "\n---\n".join(docs) if docs else "(sem documentos)"

                    sum_result = await _generate_event_summary(
                        event, outlet_list, article_excerpts_text, document_excerpts_text
                    )

                    sum_text = _extract_json_text(sum_result)
                    sum_model = sum_result.get("model", "unknown")
                    if sum_text:
                        await _store_summary(
                            conn, event_id, "event_summary", sum_text,
                            None, sum_model, SUMMARY_FAST_PROMPT_VERSION,
                        )
                        summary["summaries_generated"] += 1

                    # ── Framing comparison ──
                    outlet_excerpts = await _get_outlet_excerpts_for_framing(conn, event_id)
                    outlet_excerpts_text = "\n---\n".join(outlet_excerpts) if outlet_excerpts else "(sem artigos)"

                    framing_result = await _generate_framing_comparison(
                        event, outlet_excerpts_text
                    )

                    framing_text = _extract_framing_text(framing_result)
                    framing_model = framing_result.get("model", "unknown")
                    if framing_text:
                        await _store_summary(
                            conn, event_id, "framing_comparison", framing_text,
                            None, framing_model, FRAMING_ANALYST_PROMPT_VERSION,
                        )
                        summary["framings_generated"] += 1

                    # ── Undercoverage card (only if flag exists) ──
                    has_flags = await _has_undercoverage_flags(conn, event_id)
                    if has_flags:
                        flag_data = await _get_undercoverage_flag_data(conn, event_id)
                        if flag_data:
                            covering_slugs = await _get_event_outlets_slugs(conn, event_id)
                            covering_outlets = ", ".join(covering_slugs) if covering_slugs else "nenhum"
                            silent_outlets_text = ", ".join(flag_data["silent_outlets"][:15]) if flag_data["silent_outlets"] else "nenhum"
                            total_outlets = await _get_total_outlets(conn)

                            doc_text = "(sem documento)"
                            if flag_data.get("linked_document_id"):
                                doc_title = await conn.fetchval(
                                    "SELECT title FROM source_documents WHERE id = $1",
                                    flag_data["linked_document_id"],
                                )
                                if doc_title:
                                    doc_text = doc_title

                            uc_result = await _generate_undercoverage_card(
                                event, flag_data, covering_outlets,
                                silent_outlets_text, doc_text, total_outlets,
                            )

                            uc_text = _extract_undercoverage_text(uc_result)
                            uc_model = uc_result.get("model", "unknown")
                            if uc_text:
                                await _store_summary(
                                    conn, event_id, "undercoverage_card", uc_text,
                                    None, uc_model, UNDERCOVERAGE_CARD_PROMPT_VERSION,
                                )
                                summary["undercoverage_cards_generated"] += 1

                    logger.debug(
                        "  ✓ %s: sum=yes framing=yes ucov=%s",
                        event["canonical_title"][:50],
                        "yes" if has_flags else "no",
                    )
                except Exception as exc:
                    summary["errors"].append(
                        {"event_id": event["id"], "error": str(exc)}
                    )
                    logger.error(
                        "Error generating for event %s: %s", event["id"], exc
                    )

    logger.info(
        "Generation complete: %d summaries, %d framings, %d undercoverage cards",
        summary["summaries_generated"],
        summary["framings_generated"],
        summary["undercoverage_cards_generated"],
    )

    return summary


async def _get_event_outlets_slugs(
    conn: asyncpg.Connection, event_id: str
) -> list[str]:
    """Get outlet slugs covering this event."""
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