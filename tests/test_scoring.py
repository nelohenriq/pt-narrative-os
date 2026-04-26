"""Tests for services/scoring/scorer.py and services/enrichment/enricher.py.

Verifies:
    - Framing divergence formula.
    - Undercoverage score composite.
    - Enrichment: document linking by entity match.
    - Scoring: full pipeline on a real event.
"""

from __future__ import annotations

import pytest

from services.scoring.scorer import (
    _compute_framing_divergence,
    _compute_undercoverage_score,
    score_batch,
)
from services.enrichment.enricher import (
    enrich_batch,
)


# ══════════════════════════════════════════════════════════════════════════════
# Unit tests
# ══════════════════════════════════════════════════════════════════════════════


class TestFramingDivergence:
    """Framing divergence computation."""

    def test_all_same_frame_zero_divergence(self):
        labels = ["crise", "crise", "crise", "crise"]
        assert _compute_framing_divergence(labels) == 0.0

    def test_mixed_frames_some_divergence(self):
        labels = ["crise", "crise", "conflito", "conflito"]
        div = _compute_framing_divergence(labels)
        assert 0.49 < div < 0.51  # 1 - (2/4) = 0.5

    def test_all_different_frames_high_divergence(self):
        labels = ["crise", "conflito", "progresso", "responsabilidade"]
        div = _compute_framing_divergence(labels)
        assert div == 0.75  # 1 - (1/4) = 0.75

    def test_empty_labels_zero(self):
        assert _compute_framing_divergence([]) == 0.0

    def test_single_label_zero(self):
        assert _compute_framing_divergence(["crise"]) == 0.0


class TestUndercoverageScore:
    """Undercoverage composite score."""

    def test_low_coverage_high_undercoverage(self):
        score = _compute_undercoverage_score(
            coverage_breadth=0.1, evidence_density=0.0, lusa_dependency=0.0
        )
        # gap = 0.9, evidence_gap = 0.5
        # 0.6 * 0.9 + 0.25 * 0.5 + 0.15 * 0.0 = 0.54 + 0.125 = 0.665
        assert score == 0.665

    def test_high_coverage_low_undercoverage(self):
        score = _compute_undercoverage_score(
            coverage_breadth=0.8, evidence_density=0.9, lusa_dependency=0.0
        )
        # gap = 0.2, evidence_gap = max(0, 0.5-0.9) = 0.0
        # 0.6 * 0.2 + 0.25 * 0.0 + 0.15 * 0.0 = 0.12
        assert score == 0.12

    def test_lusa_heavy_event(self):
        score = _compute_undercoverage_score(
            coverage_breadth=0.3, evidence_density=0.3, lusa_dependency=0.9
        )
        expected = round(0.6 * 0.7 + 0.25 * 0.2 + 0.15 * 0.9, 4)
        assert score == expected

    def test_clamped_to_one(self):
        score = _compute_undercoverage_score(0.0, 0.0, 1.0)
        assert score <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# Integration tests
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestEnrichBatch:
    """End-to-end enrichment with real database."""

    @pytest.mark.asyncio
    async def test_enrich_empty_returns_gracefully(self):
        import os
        result = await enrich_batch(os.getenv("DATABASE_URL", ""))
        assert "processed" in result
        assert isinstance(result["errors"], list)

    @pytest.mark.asyncio
    async def test_enrich_event_with_source_document(self):
        """Create a source document, an event with a matching entity, and link them."""
        import os, uuid, json as _json
        import asyncpg
        from datetime import datetime, timezone

        db_url = os.getenv("DATABASE_URL", "")
        uid = uuid.uuid4().hex[:8]

        conn = await asyncpg.connect(db_url)
        try:
            # Create a source document about a specific topic
            await conn.execute(
                """
                INSERT INTO source_documents (
                    source_type, title, external_id, published_at, body_text
                ) VALUES ('government', $1, $2, now(), 'Lei sobre energia renovável')
                ON CONFLICT (source_type, external_id) DO NOTHING
                """,
                f"Lei de Bases do Clima {uid}",
                f"ext-doc-{uid}",
            )

            # Create an outlet + event that mentions "Clima"
            outlet = await conn.fetchrow("SELECT id::text FROM outlets LIMIT 1")

            article_time = datetime(2025, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
            art_id = uuid.uuid4()

            await conn.execute(
                """
                INSERT INTO articles (
                    id, outlet_id, canonical_url, url_hash, content_hash,
                    title, cleaned_text, language, word_count, status, published_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'pt', $8, 'embedded', $9)
                """,
                art_id,
                outlet["id"],
                f"https://enrich.test.com/{uid}",
                f"hash-enr-{uid}",
                f"ch-enr-{uid}",
                f"Governo aprova lei Clima {uid}",
                "Texto sobre clima e energia.",
                10,
                article_time,
            )

            # Link entity "Clima" to article_analysis
            entity_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO entities (id, name, entity_type, canonical_slug) "
                "VALUES ($1, $2, 'organization', $3) ON CONFLICT DO NOTHING",
                entity_id, f"Clima {uid}", f"clima-{uid}",
            )

            await conn.execute(
                "INSERT INTO article_entities (article_id, entity_id, confidence) "
                "VALUES ($1, $2, 0.8)",
                art_id, entity_id,
            )

            # Create an event containing this article
            event_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO events (id, canonical_title, first_seen_at, last_seen_at,
                                    article_count, outlet_count, status)
                VALUES ($1, $2, now(), now(), 1, 1, 'candidate')
                """,
                event_id, f"Evento Clima {uid}",
            )
            await conn.execute(
                "INSERT INTO event_articles (event_id, article_id, relevance_score) "
                "VALUES ($1, $2, 0.9)",
                event_id, art_id,
            )

            # Create the article_analysis for topics
            await conn.execute(
                """
                INSERT INTO article_analysis (
                    article_id, ai_run_id, analysis_json, topics
                ) VALUES (
                    $1, '00000000-0000-0000-0000-000000000001',
                    '{}'::jsonb, $2::jsonb
                )
                ON CONFLICT DO NOTHING
                """,
                art_id,
                _json.dumps(["clima", "energia"]),
            )
        finally:
            await conn.close()

        # Run enrichment
        result = await enrich_batch(db_url)
        assert result["processed"] >= 1

        conn = await asyncpg.connect(db_url)
        try:
            doc_links = await conn.fetchval(
                "SELECT count(*) FROM event_documents WHERE event_id = $1",
                event_id,
            )
            # The event has the "Clima" entity, document title contains "Clima"
            # Should link
            assert doc_links >= 1, f"Expected >=1 doc link, got {doc_links}"
        finally:
            await conn.close()


@pytest.mark.integration
class TestScoreBatch:
    """End-to-end scoring with real database."""

    @pytest.mark.asyncio
    async def test_score_event_computes_all_dimensions(self):
        """Score a real event and verify event_scores row created."""
        import os, uuid
        import asyncpg

        db_url = os.getenv("DATABASE_URL", "")
        uid = uuid.uuid4().hex[:8]

        conn = await asyncpg.connect(db_url)
        try:
            outlet = await conn.fetchrow("SELECT id::text FROM outlets LIMIT 1")

            # Create an article + event (already scored in a prior test run may exist)
            art_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO articles (
                    id, outlet_id, canonical_url, url_hash, content_hash,
                    title, cleaned_text, language, word_count, status, published_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'pt', $8, 'embedded', now())
                """,
                art_id,
                outlet["id"],
                f"https://score.test.com/{uid}",
                f"hash-sco-{uid}",
                f"ch-sco-{uid}",
                f"Notícia importante {uid}",
                "Corpo da notícia sobre um evento relevante em Portugal.",
                15,
            )

            event_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO events (id, canonical_title, first_seen_at, last_seen_at,
                                    article_count, outlet_count, status)
                VALUES ($1, $2, now(), now(), 1, 1, 'candidate')
                """,
                event_id, f"Evento {uid}",
            )
            await conn.execute(
                "INSERT INTO event_articles (event_id, article_id, relevance_score) "
                "VALUES ($1, $2, 0.9)",
                event_id, art_id,
            )

            # Give it article_analysis with frames
            await conn.execute(
                """
                INSERT INTO article_analysis (article_id, ai_run_id, analysis_json)
                VALUES ($1, '00000000-0000-0000-0000-000000000001', $2::jsonb)
                ON CONFLICT DO NOTHING
                """,
                art_id,
                '{"frame_labels": ["crise"]}',
            )
        finally:
            await conn.close()

        result = await score_batch(db_url)
        assert result["processed"] >= 1
        assert result["scored"] >= 1
        assert result["promoted"] >= 1, "Candidate should be promoted to unreviewed"

        conn = await asyncpg.connect(db_url)
        try:
            scores = await conn.fetchrow(
                "SELECT * FROM event_scores WHERE event_id = $1", event_id
            )
            assert scores is not None, "No event_scores row"
            assert scores["coverage_breadth"] is not None
            assert scores["framing_divergence"] is not None
            assert scores["evidence_density"] is not None
            assert scores["lusa_dependency"] is not None
            assert scores["undercoverage_score"] is not None

            # Event should now be 'unreviewed'
            event = await conn.fetchrow(
                "SELECT status FROM events WHERE id = $1", event_id
            )
            assert event["status"] == "unreviewed"
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_undercoverage_flag_for_low_coverage(self):
        """Low coverage event should get a flag."""
        import os, uuid
        import asyncpg

        db_url = os.getenv("DATABASE_URL", "")
        uid = uuid.uuid4().hex[:8]

        conn = await asyncpg.connect(db_url)
        try:
            outlet = await conn.fetchrow("SELECT id::text FROM outlets LIMIT 1")

            event_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO events (id, canonical_title, first_seen_at, last_seen_at,
                                    article_count, outlet_count, status)
                VALUES ($1, $2, now(), now(), 3, 1, 'candidate')
                """,
                event_id, f"Evento baixa cobertura {uid}",
            )

            # 3 articles all from the same outlet (1 outlet = very low coverage)
            for i in range(3):
                art_id = uuid.uuid4()
                await conn.execute(
                    """
                    INSERT INTO articles (
                        id, outlet_id, canonical_url, url_hash, content_hash,
                        title, cleaned_text, language, word_count, status, published_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'pt', 20, 'embedded', now())
                    """,
                    art_id,
                    outlet["id"],
                    f"https://lowcov.test.com/{uid}/{i}",
                    f"h-lc-{uid}-{i}",
                    f"ch-lc-{uid}-{i}",
                    f"Artigo {i} {uid}",
                    f"Corpo do artigo {i}",
                )
                await conn.execute(
                    "INSERT INTO event_articles (event_id, article_id, relevance_score) "
                    "VALUES ($1, $2, 0.9)",
                    event_id, art_id,
                )
                await conn.execute(
                    """
                    INSERT INTO article_analysis (article_id, ai_run_id, analysis_json)
                    VALUES ($1, '00000000-0000-0000-0000-000000000001', $2::jsonb)
                    ON CONFLICT DO NOTHING
                    """,
                    art_id, '{"frame_labels": ["crise"]}',
                )
        finally:
            await conn.close()

        result = await score_batch(db_url)
        assert result["flags_created"] >= 1, (
            f"Expected undercoverage flags for low coverage event, got {result}"
        )

        conn = await asyncpg.connect(db_url)
        try:
            flag_count = await conn.fetchval(
                "SELECT count(*) FROM undercoverage_flags WHERE event_id = $1",
                event_id,
            )
            assert flag_count >= 1
        finally:
            await conn.close()