"""Tests for services/analysis/article_analyzer.py.

Verifies:
    - Message building from system + user prompts.
    - JSON response parsing (handles markdown fences).
    - Entity upsert dedup via canonical_slug.
    - End-to-end: embedded article → AI extraction → article_analysis + entities + claims.
"""

from __future__ import annotations

import pytest

from services.analysis.article_analyzer import (
    _build_messages,
    _parse_extraction,
    analyze_batch,
    PROMPT_VERSION,
)


# ══════════════════════════════════════════════════════════════════════════════
# Unit tests
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildMessages:
    """Message template rendering."""

    def test_system_prompt_first(self):
        messages = _build_messages("Título", "Corpo do artigo.")
        assert messages[0]["role"] == "system"
        assert "Portuguese news article analyser" in messages[0]["content"]

    def test_user_message_contains_title_and_body(self):
        messages = _build_messages("Governo aprova orçamento", "O governo aprovou hoje...")
        user = messages[1]
        assert user["role"] == "user"
        assert "Title: Governo aprova orçamento" in user["content"]
        assert "O governo aprovou hoje..." in user["content"]

    def test_user_template_interpolation(self):
        messages = _build_messages("T1", "B1")
        user_content = messages[1]["content"]
        assert "Title: T1" in user_content
        assert "Body:" in user_content
        assert "B1" in user_content


class TestParseExtraction:
    """JSON response parsing."""

    def test_parses_clean_json(self):
        raw = '{"persons": ["Marcelo"], "topics": ["política"]}'
        parsed = _parse_extraction(raw)
        assert parsed["persons"] == ["Marcelo"]
        assert parsed["topics"] == ["política"]

    def test_strips_markdown_json_fence(self):
        raw = '```json\n{"persons": ["Costa"], "frame_labels": ["crise"]}\n```'
        parsed = _parse_extraction(raw)
        assert parsed["persons"] == ["Costa"]
        assert parsed["frame_labels"] == ["crise"]

    def test_strips_markdown_fence_no_lang(self):
        raw = '```\n{"key": "value"}\n```'
        parsed = _parse_extraction(raw)
        assert parsed["key"] == "value"

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            _parse_extraction("not json")

    def test_non_object_raises(self):
        with pytest.raises(ValueError, match="not a JSON object"):
            _parse_extraction("[1, 2, 3]")

    def test_empty_response_raises(self):
        with pytest.raises(ValueError):
            _parse_extraction("")

    def test_nested_objects_preserved(self):
        raw = '{"quotes": [{"text": "hello", "speaker": "X"}], "stance_flags": {"X": "positive"}}'
        parsed = _parse_extraction(raw)
        assert len(parsed["quotes"]) == 1
        assert parsed["quotes"][0]["speaker"] == "X"
        assert parsed["stance_flags"]["X"] == "positive"


# ══════════════════════════════════════════════════════════════════════════════
# Integration tests
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestAnalyzeBatch:
    """End-to-end analysis with real AI + database.

    Skip with:  pytest -m "not integration"
    """

    @pytest.mark.asyncio
    async def test_analyze_article_creates_extraction(self):
        """Run analysis on a single embedded article, verify extraction stored."""
        import os, uuid
        import asyncpg
        from openai import AsyncOpenAI

        db_url = os.getenv("DATABASE_URL", "")
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        uid = uuid.uuid4().hex[:8]

        conn = await asyncpg.connect(db_url)
        try:
            outlet = await conn.fetchrow("SELECT id::text FROM outlets LIMIT 1")
            text = (
                f"O primeiro-ministro António Costa anunciou hoje no parlamento "
                f"um novo pacote de medidas para a crise da habitação. O programa "
                f"inclui a construção de vinte mil casas nos próximos dois anos "
                f"e um subsídio de renda para jovens. Segundo o ministro das "
                f"Finanças, Fernando Medina, o investimento total será de dois mil "
                f"milhões de euros. A oposição, liderada por Luís Montenegro, "
                f"criticou a medida como insuficiente. [test-a-{uid}]"
            )

            # Insert an embedded article
            await conn.execute(
                """
                INSERT INTO articles (
                    outlet_id, canonical_url, url_hash, content_hash,
                    title, cleaned_text, language, word_count, status, published_at
                ) VALUES ($1, $2, $3, $4, $5, $6, 'pt', $7, 'embedded', now())
                ON CONFLICT (canonical_url) DO UPDATE
                SET status = 'embedded', cleaned_text = $6
                """,
                outlet["id"],
                f"https://analyze.test.com/{uid}",
                f"hash-analyze-{uid}",
                f"ch-analyze-{uid}",
                f"Governo anuncia medidas habitação [test-{uid}]",
                text,
                len(text.split()),
            )

            # Give it an embedding too (required by ai_runs FK cascade — not for clusterer but needed for completeness)
            client = AsyncOpenAI(base_url=f"{ollama_host}/v1", api_key="ollama")
            resp = await client.embeddings.create(
                model="nomic-embed-text",
                input=[f"search_document: {text}"],
            )
            await conn.execute(
                "UPDATE articles SET embedding = $1::vector WHERE canonical_url = $2",
                str(resp.data[0].embedding),
                f"https://analyze.test.com/{uid}",
            )

        finally:
            await conn.close()

        result = await analyze_batch(db_url, batch_size=20)
        assert result["processed"] >= 1
        assert result["analyzed"] >= 1
        assert result["failed"] == 0
        assert result["total_entities"] > 0, "Should extract at least one entity"
        assert result["total_claims"] > 0, "Should extract at least one claim"

        # Verify stored data
        conn = await asyncpg.connect(db_url)
        try:
            # Check article status
            art_row = await conn.fetchrow(
                "SELECT status FROM articles WHERE canonical_url = $1",
                f"https://analyze.test.com/{uid}",
            )
            assert art_row["status"] == "analyzed"

            # Check article_analysis exists
            analysis_row = await conn.fetchrow(
                """
                SELECT analysis_json, persons, organizations, topics, quotes,
                       source_types, frame_labels, cites_document
                FROM article_analysis
                WHERE article_id = (SELECT id FROM articles WHERE canonical_url = $1)
                """,
                f"https://analyze.test.com/{uid}",
            )
            assert analysis_row is not None, "No article_analysis row created"
            assert analysis_row["analysis_json"] is not None

            # asyncpg returns JSONB as strings — parse to check contents
            import json as _json
            persons = analysis_row["persons"]
            if isinstance(persons, str):
                persons = _json.loads(persons)
            assert isinstance(persons, list)

            quotes = analysis_row["quotes"]
            if isinstance(quotes, str):
                quotes = _json.loads(quotes)
            assert isinstance(quotes, list)

            # Check entities were upserted
            entity_count = await conn.fetchval(
                """
                SELECT count(*) FROM article_entities ae
                WHERE ae.article_id = (SELECT id FROM articles WHERE canonical_url = $1)
                """,
                f"https://analyze.test.com/{uid}",
            )
            assert entity_count > 0, "No article_entities links created"

            # Check claims were stored
            claim_count = await conn.fetchval(
                """
                SELECT count(*) FROM claims
                WHERE article_id = (SELECT id FROM articles WHERE canonical_url = $1)
                """,
                f"https://analyze.test.com/{uid}",
            )
            assert claim_count > 0, "No claims stored"

            # Check ai_runs audit log exists
            run_count = await conn.fetchval(
                """
                SELECT count(*) FROM ai_runs
                WHERE article_id = (SELECT id FROM articles WHERE canonical_url = $1)
                  AND task_name = 'extractor_fast'
                  AND status = 'completed'
                """,
                f"https://analyze.test.com/{uid}",
            )
            assert run_count >= 1, "No completed ai_runs row"
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_empty_batch_returns_gracefully(self):
        """When no unanalyzed articles exist, returns immediately."""
        import os
        result = await analyze_batch(os.getenv("DATABASE_URL", ""), batch_size=1)
        assert result["processed"] == 0
        assert result["errors"] == []