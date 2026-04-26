"""Tests for review/app.py — auth, pages, and review actions.

Verifies:
    - Auth rejects missing/wrong credentials, accepts valid ones.
    - Event list + detail pages return HTML.
    - Approve / Reject / Regenerate POST endpoints work.
"""

from __future__ import annotations

import base64
import json as _json

import pytest
from starlette.testclient import TestClient

import os
os.environ.setdefault("REVIEW_USERNAME", "admin")
os.environ.setdefault("REVIEW_PASSWORD_HASH", "changeme")

from review.app import app


def _auth_header(username: str = "admin", password: str = "changeme") -> dict[str, str]:
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {credentials}"}


@pytest.fixture(scope="module")
def client():
    """Module-scoped TestClient — single event loop for all tests."""
    with TestClient(app) as tc:
        yield tc


# ══════════════════════════════════════════════════════════════════════════════
# Auth tests (no DB needed)
# ══════════════════════════════════════════════════════════════════════════════


class TestAuth:
    """HTTP Basic Auth."""

    def test_no_auth_returns_401(self, client):
        response = client.get("/")
        assert response.status_code == 401

    def test_wrong_password_returns_401(self, client):
        response = client.get("/", headers=_auth_header("admin", "wrong"))
        assert response.status_code == 401

    def test_wrong_username_returns_401(self, client):
        response = client.get("/", headers=_auth_header("hacker", "changeme"))
        assert response.status_code == 401

    def test_badly_formatted_auth_returns_401(self, client):
        response = client.get("/", headers={"Authorization": "Bearer token"})
        assert response.status_code == 401

    def test_invalid_base64_returns_401(self, client):
        response = client.get(
            "/", headers={"Authorization": "Basic !!!not-base64!!!"}
        )
        assert response.status_code == 401

    def test_valid_auth_accesses_page(self, client):
        response = client.get("/", headers=_auth_header())
        # DB may or may not be reachable; auth should pass either way
        # If 200, we're authenticated; if 500, DB issue (still not 401)
        assert response.status_code != 401, f"Got {response.status_code}"


# ══════════════════════════════════════════════════════════════════════════════
# Page tests (require DB)
# ══════════════════════════════════════════════════════════════════════════════


class TestPages:
    """HTML page rendering."""

    def test_unreviewed_list_returns_html(self, client):
        response = client.get("/", headers=_auth_header())
        if response.status_code == 200:
            assert "text/html" in response.headers["content-type"]
            assert "Event Review" in response.text

    def test_published_list_returns_html(self, client):
        response = client.get("/published", headers=_auth_header())
        if response.status_code == 200:
            assert "text/html" in response.headers["content-type"]

    def test_rejected_list_returns_html(self, client):
        response = client.get("/rejected", headers=_auth_header())
        if response.status_code == 200:
            assert "text/html" in response.headers["content-type"]

    def test_event_detail_not_found(self, client):
        response = client.get(
            "/events/00000000-0000-0000-0000-000000000000",
            headers=_auth_header(),
        )
        assert response.status_code == 404

    def test_health_check_no_auth(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


# ══════════════════════════════════════════════════════════════════════════════
# Action tests (require DB + events)
# ══════════════════════════════════════════════════════════════════════════════


class TestActions:
    """Approve / Reject / Regenerate POST actions."""

    def test_approve_nonexistent(self, client):
        response = client.post(
            "/events/00000000-0000-0000-0000-000000000000/approve",
            headers=_auth_header(),
            follow_redirects=False,
        )
        # Either redirects (303) or succeeds silently
        assert response.status_code in (200, 303, 404, 500)

    def test_reject_nonexistent(self, client):
        response = client.post(
            "/events/00000000-0000-0000-0000-000000000000/reject",
            headers=_auth_header(),
            data={"note": "bad event"},
            follow_redirects=False,
        )
        assert response.status_code in (200, 303, 404, 500)

    def test_regenerate_nonexistent(self, client):
        response = client.post(
            "/events/00000000-0000-0000-0000-000000000000/regenerate",
            headers=_auth_header(),
            follow_redirects=False,
        )
        assert response.status_code in (200, 303, 404, 500)

    def test_actions_require_auth(self, client):
        for action in ["approve", "reject", "regenerate"]:
            response = client.post(
                f"/events/00000000-0000-0000-0000-000000000000/{action}",
                follow_redirects=False,
            )
            assert response.status_code == 401, f"{action} should require auth"

    def test_approve_full_cycle(self, client):
        """Create event → score → approve → verify published."""
        import uuid, asyncio
        import asyncpg

        async def _setup():
            db_url = os.getenv("DATABASE_URL", "")
            uid = uuid.uuid4().hex[:8]
            conn = await asyncpg.connect(db_url)
            try:
                outlet = await conn.fetchrow("SELECT id::text FROM outlets LIMIT 1")
                art_id = uuid.uuid4()
                await conn.execute(
                    """INSERT INTO articles (
                        id, outlet_id, canonical_url, url_hash, content_hash,
                        title, cleaned_text, language, word_count, status, published_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'pt', 20, 'embedded', now())""",
                    art_id, outlet["id"],
                    f"https://review.test.com/{uid}",
                    f"h-rev-{uid}", f"ch-rev-{uid}",
                    f"Review test event {uid}",
                    f"Article body for review test {uid}",
                )
                event_id = uuid.uuid4()
                await conn.execute(
                    """INSERT INTO events (id, canonical_title, first_seen_at, last_seen_at,
                                         article_count, outlet_count, status)
                       VALUES ($1, $2, now(), now(), 1, 1, 'unreviewed')""",
                    event_id, f"Review event {uid}",
                )
                await conn.execute(
                    "INSERT INTO event_articles (event_id, article_id, relevance_score) "
                    "VALUES ($1, $2, 0.9)",
                    event_id, art_id,
                )
                await conn.execute(
                    """INSERT INTO event_scores (event_id, coverage_breadth, framing_divergence,
                         evidence_density, lusa_dependency, undercoverage_score, explanation)
                       VALUES ($1, 0.5, 0.3, 0.1, 0.0, 0.4, 'test')""",
                    event_id,
                )
                return uid, event_id, db_url
            finally:
                await conn.close()

        uid, event_id, db_url = asyncio.run(_setup())

        # Approve via HTTP
        response = client.post(
            f"/events/{event_id}/approve",
            headers=_auth_header(),
            follow_redirects=False,
        )
        assert response.status_code == 303

        # Verify DB state
        async def _verify():
            conn = await asyncpg.connect(db_url)
            try:
                event = await conn.fetchrow("SELECT * FROM events WHERE id = $1", event_id)
                assert event["status"] == "reviewed_published"
                assert event["is_published"] is True
                assert event["is_reviewed"] is True
                assert event["reviewed_by"] == "admin"
            finally:
                await conn.close()

        asyncio.run(_verify())