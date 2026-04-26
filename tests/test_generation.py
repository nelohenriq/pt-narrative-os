"""Tests for services/generation/generator.py.

Verifies:
    - JSON extraction from AI responses (summary, framing, undercoverage).
    - Markdown fence stripping.
    - Graceful handling of missing/error states.
"""

from __future__ import annotations

import pytest

from services.generation.generator import (
    _extract_json_text,
    _extract_framing_text,
    _extract_undercoverage_text,
)


class TestExtractJsonText:
    """Summary extraction from AI responses."""

    def test_extracts_summary_key(self):
        ai_result = {
            "content": '{"summary": "O governo anunciou novas medidas económicas."}',
            "model": "deepseek-r1",
        }
        text = _extract_json_text(ai_result)
        assert text == "O governo anunciou novas medidas económicas."

    def test_returns_raw_text_if_no_summary_key(self):
        ai_result = {
            "content": "Três frases sobre o evento.",
        }
        text = _extract_json_text(ai_result)
        assert text == "Três frases sobre o evento."

    def test_error_result_returns_none(self):
        assert _extract_json_text({"error": "timeout"}) is None

    def test_empty_content_returns_none(self):
        assert _extract_json_text({"content": ""}) is None

    def test_strips_markdown_fence(self):
        ai_result = {
            "content": '```json\n{"summary": "texto"}\n```',
        }
        text = _extract_json_text(ai_result)
        assert text == "texto"


class TestExtractFramingText:
    """Framing comparison extraction."""

    def test_extracts_framing_comparison_key(self):
        ai_result = {
            "content": '{"framing_comparison": "Os jornais divergem no tom."}',
            "model": "mistral-small",
        }
        text = _extract_framing_text(ai_result)
        assert text == "Os jornais divergem no tom."

    def test_returns_raw_if_no_key(self):
        ai_result = {"content": "Análise de framing."}
        text = _extract_framing_text(ai_result)
        assert text == "Análise de framing."

    def test_error_returns_none(self):
        assert _extract_framing_text({"error": "fail"}) is None

    def test_strips_fence(self):
        ai_result = {
            "content": '```\n{"framing_comparison": "x"}\n```',
        }
        assert _extract_framing_text(ai_result) == "x"


class TestExtractUndercoverageText:
    """Undercoverage card extraction."""

    def test_extracts_undercoverage_key(self):
        ai_result = {
            "content": '{"undercoverage_explanation": "Poucos outlets cobriram."}',
            "model": "llama",
        }
        text = _extract_undercoverage_text(ai_result)
        assert text == "Poucos outlets cobriram."

    def test_error_returns_none(self):
        assert _extract_undercoverage_text({"error": "fail"}) is None

    def test_strips_fence(self):
        ai_result = {
            "content": '```json\n{"undercoverage_explanation": "explicação"}\n```',
        }
        assert _extract_undercoverage_text(ai_result) == "explicação"


# ══════════════════════════════════════════════════════════════════════════════
# Integration test (light — just verifies DB query without AI calls)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestGenerateBatch:
    """Integration test that verifies the DB polling logic works."""

    @pytest.mark.asyncio
    async def test_generate_empty_returns_gracefully(self):
        """Without AI keys or events, should return immediately."""
        import os
        os.environ.setdefault("GROQ_API_KEY", "test")
        os.environ.setdefault("NVIDIA_NIM_API_KEY", "test")
        from services.generation.generator import generate_batch
        result = await generate_batch(
            os.getenv("DATABASE_URL", ""), batch_size=1
        )
        # If there are no unreviewed+scored events, this returns immediately
        assert "processed" in result
        assert isinstance(result["errors"], list)