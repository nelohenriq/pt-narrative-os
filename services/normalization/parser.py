"""Article normalization service — HTML to structured article extraction.

Takes raw_items with status='pending', extracts body text via trafilatura,
detects language (confirms Portuguese or skips), flags explicit Lusa credit,
and inserts normalized content into the `articles` table.

Flow:
    raw_items (pending) → trafilatura extraction → language check → articles
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

import asyncpg
import trafilatura
from langdetect import DetectorFactory, detect, lang_detect_exception

logger = logging.getLogger(__name__)

# Seeds for reproducible language detection (reduces false positives for short text).
DetectorFactory.seed = 0

# Minimum word count to keep an article (from .env or default 80).
DEFAULT_MIN_WORD_COUNT = 80

# Regex patterns for explicit Lusa credit detection.
LUSA_PATTERNS = [
    re.compile(r"\bLusa\b"),
    re.compile(r"ag[a-z]*ncia\s+Lusa", re.IGNORECASE),
    re.compile(r"©\s*Lusa", re.IGNORECASE),
    re.compile(r"Lusa\s*\|", re.IGNORECASE),
    re.compile(r"via\s+Lusa", re.IGNORECASE),
    re.compile(r"Notícia\s+(da\s+)?Lusa", re.IGNORECASE),
    re.compile(r"Fotografia\s+(de\s+)?Lusa", re.IGNORECASE),
]

# ──────────────────────────────────────────────────────────────────────────────
# Extraction helpers
# ──────────────────────────────────────────────────────────────────────────────


def _extract_body(html: str, url: str | None = None) -> tuple[str | None, str | None]:
    """Extract body text and title from raw HTML using trafilatura.

    Returns (cleaned_text, title) or (None, None) on failure.
    """
    extracted = trafilatura.extract(
        html,
        output_format="txt",
        include_comments=False,
        include_tables=False,
        url=url,
    )

    if extracted is None:
        return None, None

    text = extracted.strip()
    if not text:
        return None, None

    # Also extract title
    title = None
    try:
        metadata = trafilatura.extract_metadata(
            html, default_url=url, output_format="python"
        )
        if metadata and metadata.title:
            title = metadata.title.strip()
    except Exception:
        pass

    return text, title


def _detect_language(text: str) -> str | None:
    """Detect language of the extracted text. Returns ISO 639-1 code or None."""
    # Take first 1500 chars — enough for langdetect to be reliable
    sample = text[:1500]
    try:
        return detect(sample)
    except lang_detect_exception.LangDetectException:
        return None


def _detect_lusa_credit(text: str) -> bool:
    """Check if the article explicitly credits Lusa news agency."""
    for pattern in LUSA_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _compute_content_hash(text: str) -> str:
    """SHA256 of the cleaned text for content-based dedup."""
    return hashlib.sha256(text.encode()).hexdigest()


def _normalize_newlines(text: str) -> str:
    """Collapse multiple newlines and strip whitespace."""
    return re.sub(r"\n{3,}", "\n\n", text.strip())


# ──────────────────────────────────────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────────────────────────────────────


async def _get_pending_raw_items(
    conn: asyncpg.Connection, batch_size: int = 50
) -> list[asyncpg.Record]:
    """Fetch pending raw_items that are ready for normalization."""
    rows = await conn.fetch(
        """
        SELECT id::text, outlet_id::text, canonical_url, title, raw_html, published_at, url_hash
        FROM raw_items
        WHERE status = 'pending'
        ORDER BY fetched_at
        LIMIT $1
        FOR UPDATE SKIP LOCKED
        """,
        batch_size,
    )
    return rows


async def _mark_raw_item_status(
    conn: asyncpg.Connection, raw_item_id: str, status: str, error_msg: str | None = None
) -> None:
    """Update the status of a raw_item."""
    await conn.execute(
        "UPDATE raw_items SET status = $1, error_msg = $2, updated_at = now() WHERE id = $3",
        status,
        error_msg,
        raw_item_id,
    )


async def _insert_article(
    conn: asyncpg.Connection,
    raw_item_id: str,
    outlet_id: str,
    canonical_url: str,
    url_hash: str,
    title: str,
    author: str | None,
    published_at: Any,  # datetime or None
    raw_text: str,
    cleaned_text: str,
    language: str,
    word_count: int,
    lusa_cited: bool,
) -> str:
    """Insert a new article row and return its UUID."""
    content_hash = _compute_content_hash(cleaned_text)

    # Check for content-based duplicate (same body text, different URL)
    existing = await conn.fetchrow(
        "SELECT id FROM articles WHERE content_hash = $1 LIMIT 1",
        content_hash,
    )
    if existing:
        raise ValueError(f"Content duplicate: article already exists with same body text")

    row = await conn.fetchrow(
        """
        INSERT INTO articles (
            raw_item_id, outlet_id, canonical_url, url_hash, content_hash,
            title, author, published_at, raw_text, cleaned_text,
            language, word_count, lusa_cited
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        RETURNING id::text
        """,
        raw_item_id,
        outlet_id,
        canonical_url,
        url_hash,
        content_hash,
        title,
        author,
        published_at,
        raw_text,
        cleaned_text,
        language,
        word_count,
        lusa_cited,
    )
    return row["id"]


# ──────────────────────────────────────────────────────────────────────────────
# Core normalisation pipeline
# ──────────────────────────────────────────────────────────────────────────────


async def normalize_single(
    conn: asyncpg.Connection,
    raw_item: asyncpg.Record,
    *,
    min_word_count: int | None = None,
    required_language: str | None = None,
) -> dict[str, Any]:
    """Normalize a single raw_item into an article.

    Args:
        conn: Database connection.
        raw_item: The raw_items row (must have id, outlet_id, canonical_url, title, raw_html, published_at, url_hash).
        min_word_count: Minimum words to keep. Reads MIN_ARTICLE_WORD_COUNT from env, defaults to 80.
        required_language: If set, skip articles not in this language (e.g. 'pt').
                           Defaults to 'pt' for production.

    Returns:
        dict with keys: raw_item_id, status ('parsed'|'failed'|'skipped'), article_id (if parsed),
                        word_count, language, lusa_detected, error.
    """
    raw_item_id = raw_item["id"]
    outlet_id = raw_item["outlet_id"]
    canonical_url = raw_item["canonical_url"]
    title = raw_item["title"] or ""
    raw_html = raw_item["raw_html"]
    published_at = raw_item["published_at"]
    url_hash = raw_item["url_hash"]

    if min_word_count is None:
        import os
        min_word_count = int(os.getenv("MIN_ARTICLE_WORD_COUNT", str(DEFAULT_MIN_WORD_COUNT)))

    if required_language is None:
        required_language = "pt"

    result: dict[str, Any] = {
        "raw_item_id": raw_item_id,
        "status": "pending",
        "article_id": None,
        "word_count": 0,
        "language": None,
        "lusa_detected": False,
        "error": None,
    }

    # ── 1. Fetch full HTML if we only have summary ──────────────────────────
    # In V1, raw_html from feed_reader may just be the RSS <description> field.
    # We need the real page HTML for trafilatura. If the stored HTML is short
    # (<500 chars), try fetching the article page.
    html_to_parse = raw_html or ""
    if len(html_to_parse) < 500 and canonical_url:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    canonical_url,
                    follow_redirects=True,
                    headers={"User-Agent": "pt-narrative-os/0.1"},
                )
                resp.raise_for_status()
                html_to_parse = resp.text
        except Exception:
            # Fall back to whatever we have
            pass

    # ── 2. Extract body text ────────────────────────────────────────────────
    extracted_title: str | None = None
    try:
        body_text, extracted_title = _extract_body(html_to_parse, canonical_url)
    except Exception as exc:
        logger.warning("trafilatura extraction failed for %s: %s", canonical_url, exc)
        result["status"] = "failed"
        result["error"] = str(exc)
        await _mark_raw_item_status(conn, raw_item_id, "failed", str(exc))
        return result

    if body_text is None or not body_text.strip():
        result["status"] = "failed"
        result["error"] = "No text extracted by trafilatura"
        await _mark_raw_item_status(conn, raw_item_id, "failed", "No extractable content")
        return result

    # Use extracted title if available and better than feed title
    final_title = (extracted_title or title or "Sem título").strip()
    if final_title == "Sem título" and extracted_title:
        final_title = extracted_title

    raw_text = body_text
    cleaned_text = _normalize_newlines(body_text)
    word_count = len(cleaned_text.split())

    result["word_count"] = word_count

    # ── 3. Word count filter ────────────────────────────────────────────────
    if word_count < min_word_count:
        result["status"] = "skipped"
        result["error"] = f"Too short: {word_count} words < {min_word_count}"
        await _mark_raw_item_status(conn, raw_item_id, "skipped", result["error"])
        return result

    # ── 4. Language detection ───────────────────────────────────────────────
    lang = _detect_language(cleaned_text)
    result["language"] = lang

    if required_language and lang != required_language:
        result["status"] = "skipped"
        result["error"] = f"Wrong language: {lang} != {required_language}"
        await _mark_raw_item_status(conn, raw_item_id, "skipped", result["error"])
        return result

    # ── 5. Lusa credit detection ────────────────────────────────────────────
    lusa_cited = _detect_lusa_credit(cleaned_text)
    result["lusa_detected"] = lusa_cited

    # ── 6. Insert into articles ─────────────────────────────────────────────
    try:
        article_id = await _insert_article(
            conn,
            raw_item_id=raw_item_id,
            outlet_id=outlet_id,
            canonical_url=canonical_url,
            url_hash=url_hash,
            title=final_title,
            author=None,  # trafilatura doesn't reliably extract bylines
            published_at=published_at,
            raw_text=raw_text,
            cleaned_text=cleaned_text,
            language=lang or "pt",
            word_count=word_count,
            lusa_cited=lusa_cited,
        )
        result["article_id"] = article_id
    except ValueError as exc:
        # Content duplicate — mark as skipped
        result["status"] = "skipped"
        result["error"] = f"Content duplicate: {exc}"
        await _mark_raw_item_status(conn, raw_item_id, "skipped", result["error"])
        return result
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = str(exc)
        await _mark_raw_item_status(conn, raw_item_id, "failed", str(exc))
        return result

    # ── 7. Mark raw_item as parsed ──────────────────────────────────────────
    await _mark_raw_item_status(conn, raw_item_id, "parsed")
    result["status"] = "parsed"

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Public API — batch entry point
# ──────────────────────────────────────────────────────────────────────────────


async def normalize_batch(
    db_url: str | None = None,
    *,
    batch_size: int | None = None,
    min_word_count: int | None = None,
    required_language: str | None = None,
) -> dict[str, Any]:
    """Process a batch of pending raw_items through normalization.

    Args:
        db_url: Postgres connection string. Reads from DATABASE_URL env if None.
        batch_size: Max items per run. Reads NORMALIZATION_BATCH_SIZE from env (default 50).
        min_word_count: Minimum word count. Reads MIN_ARTICLE_WORD_COUNT from env (default 80).
        required_language: Require specific language. Defaults to 'pt'.

    Returns:
        Summary dict: {processed, parsed, failed, skipped, errors}.
    """
    import os
    from dotenv import load_dotenv

    load_dotenv()

    if db_url is None:
        db_url = os.getenv("DATABASE_URL", "")

    if batch_size is None:
        batch_size = int(os.getenv("NORMALIZATION_BATCH_SIZE", "50"))

    summary: dict[str, Any] = {
        "processed": 0,
        "parsed": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
    }

    async with asyncpg.create_pool(db_url, min_size=1, max_size=3) as pool:
        async with pool.acquire() as conn:
            raw_items = await _get_pending_raw_items(conn, batch_size)

            if not raw_items:
                logger.info("No pending raw_items to normalize.")
                return summary

            logger.info("Normalizing %d pending raw_items...", len(raw_items))

            for item in raw_items:
                summary["processed"] += 1
                try:
                    result = await normalize_single(
                        conn, item,
                        min_word_count=min_word_count,
                        required_language=required_language,
                    )

                    status = result["status"]
                    if status == "parsed":
                        summary["parsed"] += 1
                        logger.debug(
                            "  ✓ %s (%d words, lang=%s, lusa=%s)",
                            item["canonical_url"][:80],
                            result["word_count"],
                            result["language"],
                            result["lusa_detected"],
                        )
                    elif status == "skipped":
                        summary["skipped"] += 1
                        logger.info(
                            "  ⊘ %s: %s",
                            item["canonical_url"][:60],
                            result["error"],
                        )
                    elif status == "failed":
                        summary["failed"] += 1
                        logger.error(
                            "  ✗ %s: %s",
                            item["canonical_url"][:60],
                            result["error"],
                        )
                        summary["errors"].append(
                            {"raw_item_id": result["raw_item_id"], "error": result["error"]}
                        )

                except Exception as exc:
                    summary["failed"] += 1
                    raw_item_id = item.get("id", "unknown")
                    summary["errors"].append({"raw_item_id": raw_item_id, "error": str(exc)})
                    logger.exception("Fatal error processing raw_item %s", raw_item_id)

    logger.info(
        "Normalization batch complete: %d processed, %d parsed, %d failed, %d skipped",
        summary["processed"],
        summary["parsed"],
        summary["failed"],
        summary["skipped"],
    )

    return summary