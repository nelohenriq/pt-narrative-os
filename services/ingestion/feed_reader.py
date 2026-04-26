"""RSS/Atom feed ingestion service for Portuguese media outlets.

Fetches feeds from outlets that have `feed_url` set in the database,
parses entries with feedparser, deduplicates by SHA256 of canonical_url,
and inserts new items into `raw_items` with status='pending'.

Outlets without feed URLs are skipped — sitemap-based fallback is handled
by the institutional.py module (Phase 2+).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg
import feedparser
import httpx

logger = logging.getLogger(__name__)

# User-agent to identify our crawler (required by many sites)
USER_AGENT = (
    "pt-narrative-os/0.1 (https://github.com/pt-narrative-os; "
    "research crawler; contact@example.com)"
)

# Typical timeouts for feed fetching
REQUEST_TIMEOUT = 30  # seconds


def _url_hash(url: str) -> str:
    """SHA256 of a canonical URL for dedup."""
    return hashlib.sha256(url.strip().encode()).hexdigest()


def _parse_published(entry: dict[str, Any]) -> datetime | None:
    """Extract the published date from a feed entry.

    feedparser provides `published_parsed` (struct_time) and `updated_parsed`.
    Returns a timezone-aware UTC datetime, or None if unparseable.
    """
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed is None:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


async def _fetch_feed(client: httpx.AsyncClient, feed_url: str) -> str | None:
    """Fetch the raw XML content of a feed. Returns None on failure."""
    try:
        resp = await client.get(
            feed_url,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError as exc:
        logger.warning("HTTP error fetching %s: %s", feed_url, exc)
        return None


async def _get_active_outlets_with_feeds(
    conn: asyncpg.Connection,
) -> list[tuple[str, str, str]]:
    """Return (id, slug, feed_url) for all active outlets that have a feed_url."""
    rows = await conn.fetch("""
        SELECT id::text, slug, feed_url
        FROM outlets
        WHERE active = TRUE AND feed_url IS NOT NULL
        ORDER BY slug
    """)
    return [(r["id"], r["slug"], r["feed_url"]) for r in rows]


async def _article_exists(conn: asyncpg.Connection, url_hash: str) -> bool:
    """Check if a url_hash already exists in raw_items."""
    row = await conn.fetchrow(
        "SELECT 1 FROM raw_items WHERE url_hash = $1 LIMIT 1", url_hash
    )
    return row is not None


async def _insert_raw_item(
    conn: asyncpg.Connection,
    outlet_id: str,
    canonical_url: str,
    url_hash: str,
    title: str | None,
    raw_html: str | None,
    published_at: datetime | None,
) -> str:
    """Insert a new raw_item row and return its UUID."""
    row = await conn.fetchrow(
        """
        INSERT INTO raw_items (outlet_id, canonical_url, url_hash, title, raw_html, published_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id::text
        """,
        outlet_id,
        canonical_url,
        url_hash,
        title,
        raw_html,
        published_at,
    )
    return row["id"]


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


async def ingest_single_feed(
    conn: asyncpg.Connection,
    outlet_id: str,
    outlet_slug: str,
    feed_url: str,
    http_client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Ingest one feed for a single outlet.

    Returns a summary dict: {slug, feed_url, fetched, inserted, skipped, error}.
    """
    summary: dict[str, Any] = {
        "slug": outlet_slug,
        "feed_url": feed_url,
        "fetched": 0,
        "inserted": 0,
        "skipped": 0,
        "error": None,
    }

    raw_xml = await _fetch_feed(http_client, feed_url)
    if raw_xml is None:
        summary["error"] = "fetch_failed"
        return summary

    parsed = feedparser.parse(raw_xml)
    if parsed.bozo and not parsed.entries:
        # bozo means feedparser hit a parse error but sometimes still has entries
        summary["error"] = f"parse_error: {parsed.bozo_exception}"
        return summary

    summary["fetched"] = len(parsed.entries)

    for entry in parsed.entries:
        canonical_url = (entry.get("link") or "").strip()
        if not canonical_url:
            summary["skipped"] += 1
            continue

        url_hash = _url_hash(canonical_url)

        # Dedup check
        if await _article_exists(conn, url_hash):
            summary["skipped"] += 1
            continue

        title = (entry.get("title") or "").strip() or None
        published_at = _parse_published(entry)
        raw_html = entry.get("summary") or entry.get("content", [{}])[0].get("value", None)  # type: ignore[union-attr]

        await _insert_raw_item(
            conn, outlet_id, canonical_url, url_hash, title, raw_html, published_at
        )
        summary["inserted"] += 1

    return summary


async def ingest_all_feeds(
    db_url: str | None = None,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Ingest all active outlet feeds.

    This is the main entry point called by the scheduler.

    Args:
        db_url: Postgres connection string. Reads from DATABASE_URL env if None.
        http_client: Shared httpx client. Creates one if None.

    Returns:
        List of per-outcome summary dicts.
    """
    import os

    from dotenv import load_dotenv

    load_dotenv()

    if db_url is None:
        db_url = os.getenv("DATABASE_URL", "")

    async with asyncpg.create_pool(db_url, min_size=1, max_size=5) as pool:
        async with pool.acquire() as conn:
            outlets = await _get_active_outlets_with_feeds(conn)

    if not outlets:
        logger.info("No active outlets with feed_urls found.")
        return []

    results: list[dict[str, Any]] = []
    own_client = http_client is None

    if own_client:
        http_client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )

    try:
        async with asyncpg.create_pool(db_url, min_size=1, max_size=5) as pool:
            for outlet_id, slug, feed_url in outlets:
                try:
                    async with pool.acquire() as conn:
                        summary = await ingest_single_feed(
                            conn, outlet_id, slug, feed_url, http_client
                        )
                    results.append(summary)

                    if summary["error"]:
                        logger.warning(
                            "Feed %s: %s (fetched=%d, inserted=%d, skipped=%d)",
                            slug,
                            summary["error"],
                            summary["fetched"],
                            summary["inserted"],
                            summary["skipped"],
                        )
                    else:
                        logger.info(
                            "Feed %s: fetched=%d, inserted=%d, skipped=%d",
                            slug,
                            summary["fetched"],
                            summary["inserted"],
                            summary["skipped"],
                        )
                except Exception as exc:
                    logger.error("Unexpected error processing feed %s: %s", slug, exc)
                    results.append(
                        {
                            "slug": slug,
                            "feed_url": feed_url,
                            "fetched": 0,
                            "inserted": 0,
                            "skipped": 0,
                            "error": str(exc),
                        }
                    )
    finally:
        if own_client and http_client:
            await http_client.aclose()

    # Log totals
    total_fetched = sum(r["fetched"] for r in results)
    total_inserted = sum(r["inserted"] for r in results)
    total_skipped = sum(r["skipped"] for r in results)
    total_errors = sum(1 for r in results if r["error"])
    logger.info(
        "Ingestion complete: %d outlets, %d fetched, %d inserted, %d skipped, %d errors",
        len(results),
        total_fetched,
        total_inserted,
        total_skipped,
        total_errors,
    )

    return results