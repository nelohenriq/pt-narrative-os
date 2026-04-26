"""Tests for services/clustering/embedder.py and clusterer.py.

Verifies:
    - Cosine similarity computation.
    - Centroid computation.
    - Vector string parsing.
    - Embedding generation via Ollama (integration).
    - End-to-end clustering: embed → cluster → event created.
"""

from __future__ import annotations

import pytest

from services.clustering.embedder import (
    _centroid,
    _cosine_similarity,
    embed_batch,
)
from services.clustering.clusterer import (
    _parse_vector_string,
    cluster_batch,
)


# ══════════════════════════════════════════════════════════════════════════════
# Unit tests
# ══════════════════════════════════════════════════════════════════════════════


class TestCosineSimilarity:
    """Cosine similarity between embedding vectors."""

    def test_identical_vectors(self):
        v = [0.1, 0.2, 0.3, 0.4]
        sim = _cosine_similarity(v, v)
        assert sim == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors(self):
        v1 = [1.0, 0.0, 0.0]
        v2 = [0.0, 1.0, 0.0]
        sim = _cosine_similarity(v1, v2)
        assert sim == pytest.approx(0.0, abs=1e-6)

    def test_opposite_vectors(self):
        v1 = [1.0, 0.0]
        v2 = [-1.0, 0.0]
        sim = _cosine_similarity(v1, v2)
        assert sim == pytest.approx(-1.0, abs=1e-6)

    def test_partial_similarity(self):
        v1 = [0.5, 0.5, 0.5]
        v2 = [0.5, 0.5, 0.4]
        sim = _cosine_similarity(v1, v2)
        assert 0.9 < sim < 1.0

    def test_zero_vector(self):
        v1 = [0.0, 0.0, 0.0]
        v2 = [1.0, 2.0, 3.0]
        sim = _cosine_similarity(v1, v2)
        assert sim == 0.0


class TestCentroid:
    """Centroid computation."""

    def test_single_vector(self):
        v = [0.1, 0.2, 0.3]
        c = _centroid([v])
        assert c == pytest.approx(v)

    def test_two_vectors(self):
        v1 = [1.0, 0.0]
        v2 = [0.0, 1.0]
        c = _centroid([v1, v2])
        assert c == pytest.approx([0.5, 0.5])

    def test_three_vectors(self):
        v1 = [1.0, 2.0]
        v2 = [3.0, 4.0]
        v3 = [5.0, 6.0]
        c = _centroid([v1, v2, v3])
        assert c == pytest.approx([3.0, 4.0])

    def test_empty_returns_zeros(self):
        c = _centroid([])
        assert len(c) == 768
        assert sum(c) == 0.0


class TestParseVector:
    """pgvector string parsing."""

    def test_valid_vector(self):
        s = "[0.1, 0.2, 0.3]"
        result = _parse_vector_string(s)
        assert result == pytest.approx([0.1, 0.2, 0.3])

    def test_with_spaces(self):
        s = "[0.1,  0.2 , 0.3]"
        result = _parse_vector_string(s)
        assert result == pytest.approx([0.1, 0.2, 0.3])

    def test_none_input(self):
        assert _parse_vector_string(None) is None

    def test_empty_string(self):
        assert _parse_vector_string("") is None

    def test_invalid_format(self):
        assert _parse_vector_string("not a vector") is None


# ══════════════════════════════════════════════════════════════════════════════
# Integration tests
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestEmbedBatch:
    """End-to-end embedding with real Ollama and database.

    Skip with:  pytest -m "not integration"
    """

    @pytest.mark.asyncio
    async def test_embed_articles_success(self):
        """Embed a real article and verify 768-dim vector stored."""
        import os, uuid
        import asyncpg
        from dotenv import load_dotenv

        load_dotenv()
        db_url = os.getenv("DATABASE_URL", "")

        conn = await asyncpg.connect(db_url)
        try:
            outlet = await conn.fetchrow("SELECT id::text FROM outlets LIMIT 1")
            uid = uuid.uuid4().hex[:8]
            text = (
                f"O governo português anunciou hoje um novo conjunto de medidas "
                f"económicas para apoiar as famílias durante a crise energética. "
                f"As medidas incluem redução do IVA nos bens essenciais e apoios "
                f"diretos às rendas. O primeiro-ministro afirmou que o pacote "
                f"representa um investimento de mais de mil milhões de euros "
                f"e entrará em vigor no próximo mês. A oposição já criticou "
                f"as medidas, considerando-as insuficientes face à gravidade "
                f"da situação. Os sindicatos também se manifestaram, exigindo "
                f"aumentos salariais acima da inflação. [test-{uid}]"
            )

            await conn.execute(
                """
                INSERT INTO articles (
                    outlet_id, canonical_url, url_hash, content_hash,
                    title, cleaned_text, language, word_count, status, published_at
                ) VALUES ($1, $2, $3, $4, $5, $6, 'pt', $7, 'pending', now())
                ON CONFLICT (canonical_url) DO UPDATE
                SET status = 'pending', published_at = now()
                """,
                outlet["id"],
                f"https://embed.test.com/{uid}",
                f"hash-embed-{uid}",
                f"ch-embed-{uid}",
                f"Governo aprova medidas [test-{uid}]",
                text,
                len(text.split()),
            )
        finally:
            await conn.close()

        result = await embed_batch(db_url, batch_size=50)
        assert result["processed"] >= 1
        assert result["embedded"] >= 1
        assert result["failed"] == 0

        conn = await asyncpg.connect(db_url)
        try:
            article = await conn.fetchrow(
                "SELECT embedding, status FROM articles WHERE canonical_url = $1",
                f"https://embed.test.com/{uid}",
            )
            assert article is not None
            assert article["status"] == "embedded"
            assert article["embedding"] is not None

            emb_str = str(article["embedding"])
            emb = _parse_vector_string(emb_str)
            assert emb is not None
            assert len(emb) == 768, f"Expected 768 dim, got {len(emb)}"
        finally:
            await conn.close()


@pytest.mark.integration
class TestClusterBatch:
    """End-to-end clustering with real database.

    Requires articles with embeddings.
    """

    @pytest.mark.asyncio
    async def test_cluster_creates_event(self):
        """Clustering an embedded article should create a new event."""
        import os, uuid, datetime as _dt
        import asyncpg
        from dotenv import load_dotenv
        from openai import AsyncOpenAI

        load_dotenv()
        db_url = os.getenv("DATABASE_URL", "")

        # Use a distinctive topic + set article published_at to an isolated time
        # so it doesn't match existing events
        conn = await asyncpg.connect(db_url)
        try:
            outlet = await conn.fetchrow("SELECT id::text FROM outlets LIMIT 1")
            uid = uuid.uuid4().hex[:8]
            topic_tag = uuid.uuid4().hex
            old_time = _dt.datetime.now(tz=_dt.timezone.utc) - _dt.timedelta(days=730)
            text = (
                f"Descoberta arqueológica única no vale do Côa revela pinturas "
                f"rupestres com mais de trinta mil anos. Os arqueólogos da "
                f"Universidade do Porto encontraram mais de cinquenta novas "
                f"gravuras numa gruta até agora desconhecida. {topic_tag}"
            )

            await conn.execute(
                """
                INSERT INTO articles (
                    outlet_id, canonical_url, url_hash, content_hash,
                    title, cleaned_text, language, word_count, status, published_at, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, 'pt', $7, 'pending', $8, $8)
                ON CONFLICT (canonical_url) DO UPDATE
                SET status = 'pending', published_at = $8, created_at = $8
                """,
                outlet["id"],
                f"https://cluster.test.com/{uid}",
                f"hash-cluster-{uid}",
                f"ch-cluster-{uid}",
                f"Descoberta arqueológica Côa [test-{uid}]",
                text,
                len(text.split()),
                old_time,
            )

            client = AsyncOpenAI(
                base_url=f"{os.getenv('OLLAMA_HOST', 'http://localhost:11434')}/v1",
                api_key="ollama",
            )
            resp = await client.embeddings.create(
                model="nomic-embed-text",
                input=[f"search_document: {text}"],
            )
            emb = resp.data[0].embedding

            await conn.execute(
                """UPDATE articles SET embedding = $1::vector, status = 'embedded'
                   WHERE canonical_url = $2""",
                str(emb),
                f"https://cluster.test.com/{uid}",
            )

        finally:
            await conn.close()

        result = await cluster_batch(db_url, batch_size=50)
        assert result["processed"] >= 1
        assert result["events_created"] >= 1
        assert result["clustered"] >= 1

        conn = await asyncpg.connect(db_url)
        try:
            event_row = await conn.fetchrow(
                """SELECT e.id, e.canonical_title, e.article_count, e.status
                   FROM events e
                   JOIN event_articles ea ON ea.event_id = e.id
                   JOIN articles a ON a.id = ea.article_id
                   WHERE a.canonical_url = $1 LIMIT 1""",
                f"https://cluster.test.com/{uid}",
            )
            assert event_row is not None, "No event found"
            assert event_row["status"] == "candidate"
            assert event_row["article_count"] >= 1
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_similar_articles_cluster_together(self):
        """Two articles about same topic should end up in same event."""
        import os, uuid, datetime as _dt
        import asyncpg
        from dotenv import load_dotenv
        from openai import AsyncOpenAI

        load_dotenv()
        db_url = os.getenv("DATABASE_URL", "")
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        client = AsyncOpenAI(base_url=f"{ollama_host}/v1", api_key="ollama")
        uid = uuid.uuid4().hex[:8]
        topic_tag = uuid.uuid4().hex
        old_time = _dt.datetime.now(tz=_dt.timezone.utc) - _dt.timedelta(days=365)

        text1 = (
            f"Festival internacional de cinema de animação em Espinho atrai "
            f"mais de dez mil visitantes na sua vigésima edição. O evento "
            f"contou com a presença de realizadores de vinte países. {topic_tag}"
        )
        text2 = (
            f"Festival internacional de cinema de animação em Espinho atrai "
            f"mais de dez mil visitantes na sua vigésima edição. O evento "
            f"contou com a presença de realizadores de vinte países. {uuid.uuid4().hex}"
        )

        # Round 1: insert + embed article 0, then cluster
        conn = await asyncpg.connect(db_url)
        try:
            outlet_row = await conn.fetchrow("SELECT id::text FROM outlets LIMIT 1")
            await conn.execute(
                """
                INSERT INTO articles (
                    outlet_id, canonical_url, url_hash, content_hash,
                    title, cleaned_text, language, word_count, status, published_at, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, 'pt', $7, 'pending', $8, $8)
                ON CONFLICT (canonical_url) DO UPDATE
                SET status = 'pending', published_at = $8, created_at = $8
                """,
                outlet_row["id"],
                f"https://similar.test.com/{uid}-0",
                f"hash-sim-{uid}-0",
                f"ch-sim-{uid}-0",
                f"Festival animação A [test-{uid}]",
                text1,
                len(text1.split()),
                old_time,
            )
            resp = await client.embeddings.create(
                model="nomic-embed-text", input=[f"search_document: {text1}"],
            )
            await conn.execute(
                """UPDATE articles SET embedding = $1::vector, status = 'embedded'
                   WHERE canonical_url = $2""",
                str(resp.data[0].embedding),
                f"https://similar.test.com/{uid}-0",
            )

        finally:
            await conn.close()

        result1 = await cluster_batch(db_url, batch_size=50)
        assert result1["events_created"] >= 1

        # Round 2: insert + embed article 1, then cluster (should join)
        conn = await asyncpg.connect(db_url)
        try:
            outlet_row2 = await conn.fetchrow("SELECT id::text FROM outlets LIMIT 1")
            await conn.execute(
                """
                INSERT INTO articles (
                    outlet_id, canonical_url, url_hash, content_hash,
                    title, cleaned_text, language, word_count, status, published_at, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, 'pt', $7, 'pending', $8, $8)
                ON CONFLICT (canonical_url) DO UPDATE
                SET status = 'pending', published_at = $8, created_at = $8
                """,
                outlet_row2["id"],
                f"https://similar.test.com/{uid}-1",
                f"hash-sim-{uid}-1",
                f"ch-sim-{uid}-1",
                f"Festival animação B [test-{uid}]",
                text2,
                len(text2.split()),
                old_time,
            )
            resp2 = await client.embeddings.create(
                model="nomic-embed-text", input=[f"search_document: {text2}"],
            )
            await conn.execute(
                """UPDATE articles SET embedding = $1::vector, status = 'embedded'
                   WHERE canonical_url = $2""",
                str(resp2.data[0].embedding),
                f"https://similar.test.com/{uid}-1",
            )

        finally:
            await conn.close()

        result2 = await cluster_batch(db_url, batch_size=50)
        assert result2["events_joined"] >= 1

        # Verify both in same event
        conn = await asyncpg.connect(db_url)
        try:
            rows = await conn.fetch(
                """SELECT ea.event_id FROM event_articles ea
                   JOIN articles a ON a.id = ea.article_id
                   WHERE a.canonical_url IN ($1, $2)""",
                f"https://similar.test.com/{uid}-0",
                f"https://similar.test.com/{uid}-1",
            )
            event_ids = {r["event_id"] for r in rows}
            assert len(event_ids) == 1, f"Expected 1 event, got {len(event_ids)}"
        finally:
            await conn.close()