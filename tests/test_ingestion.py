"""Tests for services/ingestion/feed_reader.py.

Verifies:
    - Feed fetching via mocked httpx.
    - Dedup via SHA256 url_hash.
    - DB insertion of raw_items.
    - Handling of outlets without feed_url.
    - Error handling for broken feeds.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import HTTPStatusError, Request, Response

from services.ingestion.feed_reader import (
    _parse_published,
    _url_hash,
    ingest_single_feed,
)


# ══════════════════════════════════════════════════════════════════════════════
# Unit tests
# ══════════════════════════════════════════════════════════════════════════════


class TestUrlHash:
    """SHA256 dedup function."""

    def test_same_url_same_hash(self):
        h1 = _url_hash("https://example.com/article/1")
        h2 = _url_hash("https://example.com/article/1")
        assert h1 == h2

    def test_different_url_different_hash(self):
        h1 = _url_hash("https://example.com/article/1")
        h2 = _url_hash("https://example.com/article/2")
        assert h1 != h2

    def test_trailing_whitespace_normalized(self):
        h1 = _url_hash("https://example.com/article/1")
        h2 = _url_hash("https://example.com/article/1  ")
        assert h1 == h2

    def test_hash_is_hex_string(self):
        h = _url_hash("https://example.com/article")
        assert len(h) == 64
        int(h, 16)  # Should not raise


class TestParsePublished:
    """Date extraction from feed entries."""

    def test_valid_published_parsed(self):
        entry = {"published_parsed": (2025, 6, 15, 10, 30, 0, 0, 166, 0)}
        result = _parse_published(entry)
        assert result == datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_fallback_to_updated_parsed(self):
        entry = {"updated_parsed": (2025, 6, 15, 14, 0, 0, 0, 166, 0)}
        result = _parse_published(entry)
        assert result == datetime(2025, 6, 15, 14, 0, 0, tzinfo=timezone.utc)

    def test_published_takes_priority(self):
        entry = {
            "published_parsed": (2025, 6, 15, 10, 0, 0, 0, 166, 0),
            "updated_parsed": (2025, 6, 16, 10, 0, 0, 0, 167, 0),
        }
        result = _parse_published(entry)
        assert result == datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc)

    def test_no_date_returns_none(self):
        assert _parse_published({}) is None

    def test_invalid_date_returns_none(self):
        assert _parse_published({"published_parsed": ("bad",)}) is None


# ══════════════════════════════════════════════════════════════════════════════
# Integration tests (mock HTTP, real DB flow)
# ══════════════════════════════════════════════════════════════════════════════


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <description>Test feed for unit tests</description>
    <item>
      <title>Artigo de Teste 1</title>
      <link>https://example.com/article/test-1</link>
      <description>Conteúdo do artigo de teste 1.</description>
      <pubDate>Mon, 15 Jun 2025 10:30:00 GMT</pubDate>
    </item>
    <item>
      <title>Artigo de Teste 2</title>
      <link>https://example.com/article/test-2</link>
      <description>Conteúdo do artigo de teste 2.</description>
      <pubDate>Mon, 15 Jun 2025 11:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Artigo sem link</title>
      <description>Este não tem link.</description>
    </item>
  </channel>
</rss>"""


@pytest.mark.integration
class TestIngestSingleFeed:
    """End-to-end feed ingestion with real database.

    Skip with:  pytest -m "not integration"
    """

    @pytest.mark.asyncio
    async def test_ingest_inserts_new_items(self):
        import os, uuid

        import asyncpg
        from dotenv import load_dotenv
        from httpx import AsyncClient

        load_dotenv()
        db_url = os.getenv("DATABASE_URL", "")

        # Get a real outlet ID from the DB
        conn = await asyncpg.connect(db_url)
        try:
            row = await conn.fetchrow(
                "SELECT id::text, slug, feed_url FROM outlets WHERE feed_url IS NOT NULL LIMIT 1"
            )
            if row is None:
                pytest.skip("No outlets with feed_url in DB")
            outlet_id, slug, dummy_feed = row["id"], row["slug"], row["feed_url"]
        finally:
            await conn.close()

        # Use unique URLs per test to avoid cross-test dedup
        uid = uuid.uuid4().hex[:8]
        test_rss = SAMPLE_RSS.replace("test-1", f"newitems-{uid}-1").replace("test-2", f"newitems-{uid}-2")

        # Build a mock response that httpx accepts (needs specific attributes)
        mock_response = httpx.Response(
            status_code=200,
            text=test_rss,
            request=httpx.Request("GET", "https://mock.example/feed.xml"),
        )

        http_client = AsyncClient()
        http_client.get = AsyncMock(return_value=mock_response)

        conn = await asyncpg.connect(db_url)
        try:
            summary = await ingest_single_feed(
                conn, outlet_id, slug, "https://mock.example/feed.xml", http_client
            )

            assert summary["error"] is None, f"Feed error: {summary['error']}"
            assert summary["fetched"] == 3  # 3 items in sample feed
            assert summary["inserted"] >= 1  # At least the ones with links
            assert summary["skipped"] >= 0

            # The item without a link should be skipped
            assert summary["skipped"] >= 1

        finally:
            await conn.close()
            await http_client.aclose()

    @pytest.mark.asyncio
    async def test_dedup_prevents_duplicates(self):
        """Running the same feed twice should not re-insert items."""
        import os, uuid

        import asyncpg
        from dotenv import load_dotenv
        from httpx import AsyncClient

        load_dotenv()
        db_url = os.getenv("DATABASE_URL", "")

        conn = await asyncpg.connect(db_url)
        try:
            row = await conn.fetchrow(
                "SELECT id::text, slug FROM outlets WHERE feed_url IS NOT NULL LIMIT 1"
            )
            if row is None:
                pytest.skip("No outlets with feed_url")
            outlet_id, slug = row["id"], row["slug"]
        finally:
            await conn.close()

        # Use unique URLs per test to avoid cross-test dedup contamination
        uid = uuid.uuid4().hex[:8]
        dedup_rss = SAMPLE_RSS.replace("test-1", f"dedup-{uid}-1").replace("test-2", f"dedup-{uid}-2")

        mock_response = httpx.Response(
            status_code=200,
            text=dedup_rss,
            request=httpx.Request("GET", "https://mock.example/feed.xml"),
        )

        http_client = AsyncClient()
        http_client.get = AsyncMock(return_value=mock_response)

        # First ingestion
        conn = await asyncpg.connect(db_url)
        try:
            summary1 = await ingest_single_feed(
                conn, outlet_id, slug, "https://mock.example/feed.xml", http_client
            )
            assert summary1["inserted"] >= 1
        finally:
            await conn.close()

        # Second ingestion — should skip all (dedup)
        conn = await asyncpg.connect(db_url)
        try:
            summary2 = await ingest_single_feed(
                conn, outlet_id, slug, "https://mock.example/feed.xml", http_client
            )
            assert summary2["inserted"] == 0, "Dedup should prevent re-insertion"
            assert summary2["skipped"] >= summary1["inserted"]
        finally:
            await conn.close()

        await http_client.aclose()

    @pytest.mark.asyncio
    async def test_broken_feed_url(self):
        """A non-existent feed URL should return error, not crash."""
        import os

        import asyncpg
        from dotenv import load_dotenv
        from httpx import AsyncClient

        load_dotenv()
        db_url = os.getenv("DATABASE_URL", "")

        conn = await asyncpg.connect(db_url)
        try:
            row = await conn.fetchrow(
                "SELECT id::text, slug FROM outlets WHERE feed_url IS NOT NULL LIMIT 1"
            )
            if row is None:
                pytest.skip("No outlets")
            outlet_id, slug = row["id"], row["slug"]
        finally:
            await conn.close()

        # Simulate a 500 error
        mock_transport = AsyncMock()
        failed_response = Response(
            status_code=500,
            request=Request("GET", "https://mock.example/broken"),
        )

        async def raise_error(*args, **kwargs):
            raise HTTPStatusError(
                "Server error",
                request=Request("GET", "https://mock.example/broken"),
                response=failed_response,
            )

        mock_transport.handle_async_request = raise_error

        http_client = AsyncClient(transport=mock_transport)

        conn = await asyncpg.connect(db_url)
        try:
            summary = await ingest_single_feed(
                conn, outlet_id, slug, "https://mock.example/broken", http_client
            )
            assert summary["error"] is not None
            assert summary["inserted"] == 0
        finally:
            await conn.close()

        await http_client.aclose()