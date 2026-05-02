#!/usr/bin/env python3
"""Reproduce test_similar_articles_cluster_together with verbose logging."""
import asyncio, os, uuid, datetime as _dt, logging
import asyncpg
from dotenv import load_dotenv
from openai import AsyncOpenAI
from services.clustering.clusterer import cluster_batch, _get_unclustered_articles, _find_nearest_event, _parse_vector_string, _cosine_similarity

logging.basicConfig(level=logging.DEBUG)

async def main():
    load_dotenv()
    db_url = os.getenv('DATABASE_URL', '')
    ollama_host = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
    client = AsyncOpenAI(base_url=f'{ollama_host}/v1', api_key='ollama')

    uid = uuid.uuid4().hex[:8]
    token = uuid.uuid4().hex
    old_time = _dt.datetime.now(tz=_dt.timezone.utc) - _dt.timedelta(days=365)

    text1 = (
        f'A nova aplicação móvel {token} desenvolvida por estudantes da '
        f'Universidade do Minho venceu o concurso nacional de inovação '
        f'tecnológica. A aplicação utiliza inteligência artificial para '
        f'otimizar rotas de transportes públicos.'
    )
    text2 = (
        f'A aplicação móvel {token} dos estudantes do Minho que ganhou '
        f'o prémio nacional de inovação vai ser implementada em mais '
        f'cinco cidades portuguesas até ao final do ano.'
    )

    # Round 1: insert + embed article 0, then cluster
    print('=== ROUND 1 ===')
    conn = await asyncpg.connect(db_url)
    try:
        outlet_row = await conn.fetchrow('SELECT id::text FROM outlets LIMIT 1')
        await conn.execute(
            """INSERT INTO articles (
                outlet_id, canonical_url, url_hash, content_hash,
                title, cleaned_text, language, word_count, status, published_at, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, 'pt', $7, 'pending', $8, $8)
            ON CONFLICT (canonical_url) DO UPDATE
            SET status = 'pending', published_at = $8, created_at = $8""",
            outlet_row['id'], f'https://diag2.test.com/{uid}-0',
            f'hash-{uid}-0', f'ch-{uid}-0',
            f'App transportes A {token[:12]} [test-{uid}]',
            text1, len(text1.split()), old_time,
        )
        resp = await client.embeddings.create(
            model='nomic-embed-text', input=[f'search_document: {text1}'],
        )
        emb0 = resp.data[0].embedding
        await conn.execute(
            """UPDATE articles SET embedding = $1::vector, status = 'embedded'
               WHERE canonical_url = $2""",
            str(emb0), f'https://diag2.test.com/{uid}-0',
        )
        print(f'  Article 0 inserted + embedded, emb dims={len(emb0)}')
    finally:
        await conn.close()

    result1 = await cluster_batch(db_url, batch_size=50)
    print(f'  cluster_batch result: {result1}')
    assert result1['events_created'] >= 1, f'FAIL: {result1}'

    # Inspect what was created
    conn = await asyncpg.connect(db_url)
    try:
        events = await conn.fetch("""SELECT id::text, canonical_title, centroid::text as c,
            first_seen_at, last_seen_at FROM events WHERE canonical_title LIKE $1""", f'%{uid}%')
        print(f'  Events matching uid: {len(events)}')
        for e in events:
            centroid = _parse_vector_string(e['c'])
            sim = _cosine_similarity(emb0, centroid or [0.0]*768)
            print(f'    id={e["id"][:12]} title={e["canonical_title"][:60]} '
                  f'first={e["first_seen_at"]} last={e["last_seen_at"]} sim_to_a0={sim:.4f}')
    finally:
        await conn.close()

    # Round 2: insert article 1
    print('\n=== ROUND 2 ===')
    conn = await asyncpg.connect(db_url)
    try:
        outlet_row2 = await conn.fetchrow('SELECT id::text FROM outlets LIMIT 1')
        await conn.execute(
            """INSERT INTO articles (
                outlet_id, canonical_url, url_hash, content_hash,
                title, cleaned_text, language, word_count, status, published_at, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, 'pt', $7, 'pending', $8, $8)
            ON CONFLICT (canonical_url) DO UPDATE
            SET status = 'pending', published_at = $8, created_at = $8""",
            outlet_row2['id'], f'https://diag2.test.com/{uid}-1',
            f'hash-{uid}-1', f'ch-{uid}-1',
            f'App transportes B {token[:12]} [test-{uid}]',
            text2, len(text2.split()), old_time,
        )
        resp2 = await client.embeddings.create(
            model='nomic-embed-text', input=[f'search_document: {text2}'],
        )
        emb1 = resp2.data[0].embedding
        await conn.execute(
            """UPDATE articles SET embedding = $1::vector, status = 'embedded'
               WHERE canonical_url = $2""",
            str(emb1), f'https://diag2.test.com/{uid}-1',
        )
        print(f'  Article 1 inserted + embedded, emb dims={len(emb1)}')
    finally:
        await conn.close()

    # Manually check what _find_nearest_event would return
    print('\n  Checking _find_nearest_event manually:')
    conn = await asyncpg.connect(db_url)
    try:
        # Get the event from round 1
        events_all = await conn.fetch('SELECT id::text, canonical_title, centroid::text, first_seen_at, last_seen_at, COALESCE(last_seen_at, created_at) as eff_ts FROM events')
        print(f'  All events ({len(events_all)}):')
        for e in events_all:
            centroid = _parse_vector_string(e['centroid::text'])
            sim = _cosine_similarity(emb1, centroid or [0.0]*768)
            in_window = (old_time - _dt.timedelta(hours=72)) <= e['eff_ts']
            print(f'    {e["id"][:12]} title={e["canonical_title"][:50]} eff_ts={e["eff_ts"]} '
                  f'in_window={in_window} sim_to_a1={sim:.4f}')
    finally:
        await conn.close()

    result2 = await cluster_batch(db_url, batch_size=50)
    print(f'  cluster_batch result: {result2}')

asyncio.run(main())