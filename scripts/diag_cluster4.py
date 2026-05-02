#!/usr/bin/env python3
"""Debug test_similar_articles_cluster_together with monkey-patched logging."""
import asyncio, os, uuid, datetime as _dt, logging
import asyncpg
from dotenv import load_dotenv
from openai import AsyncOpenAI
from services.clustering.clusterer import cluster_batch
import services.clustering.clusterer as clustermod

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
        f'otimizar rotas de transportes públicos em cidades de média '
        f'dimensão e já está a ser testada em Braga e Guimarães.'
    )
    text2 = (
        f'A aplicação móvel {token} dos estudantes do Minho que ganhou '
        f'o prémio nacional de inovação vai ser implementada em mais '
        f'cinco cidades portuguesas até ao final do ano. O projeto '
        f'recebeu também financiamento europeu de dois milhões de euros '
        f'para expandir a tecnologia de otimização de transportes.'
    )

    # Round 1
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
            outlet_row['id'], f'https://dbg.test.com/{uid}-0',
            f'hash-{uid}-0', f'ch-{uid}-0',
            f'App transportes A {token[:12]} [test-{uid}]',
            text1, len(text1.split()), old_time,
        )
        resp = await client.embeddings.create(
            model='nomic-embed-text', input=[f'search_document: {text1}'],
        )
        await conn.execute(
            """UPDATE articles SET embedding = $1::vector, status = 'embedded'
               WHERE canonical_url = $2""",
            str(resp.data[0].embedding), f'https://dbg.test.com/{uid}-0',
        )
    finally:
        await conn.close()

    result1 = await cluster_batch(db_url, batch_size=50)
    print(f'  R1 result: {result1}')
    assert result1['events_created'] >= 1, f'R1 FAIL: {result1}'

    # Check DB state after round 1
    conn = await asyncpg.connect(db_url)
    try:
        events = await conn.fetch('SELECT id::text, canonical_title, first_seen_at, last_seen_at, created_at FROM events')
        print(f'  Events after R1 ({len(events)}):')
        for e in events:
            print(f'    id={e["id"][:12]} title={e["canonical_title"][:60]} '
                  f'first={e["first_seen_at"]} last={e["last_seen_at"]} created={e["created_at"]}')

        eas = await conn.fetch('SELECT ea.event_id::text, a.canonical_url FROM event_articles ea JOIN articles a ON a.id = ea.article_id')
        print(f'  Event-article links after R1 ({len(eas)}):')
        for ea in eas:
            print(f'    event={ea["event_id"][:12]} url={ea["canonical_url"]}')
    finally:
        await conn.close()

    # Round 2
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
            outlet_row2['id'], f'https://dbg.test.com/{uid}-1',
            f'hash-{uid}-1', f'ch-{uid}-1',
            f'App transportes B {token[:12]} [test-{uid}]',
            text2, len(text2.split()), old_time,
        )
        resp2 = await client.embeddings.create(
            model='nomic-embed-text', input=[f'search_document: {text2}'],
        )
        await conn.execute(
            """UPDATE articles SET embedding = $1::vector, status = 'embedded'
               WHERE canonical_url = $2""",
            str(resp2.data[0].embedding), f'https://dbg.test.com/{uid}-1',
        )
        print(f'  Article 1 inserted + embedded')
    finally:
        await conn.close()

    # Manually verify what _find_nearest_event would see
    conn = await asyncpg.connect(db_url)
    try:
        since = old_time - _dt.timedelta(hours=72)
        print(f'  since = {since}')
        events = await conn.fetch(
            """SELECT id::text, canonical_title, centroid::text, 
               COALESCE(last_seen_at, created_at) AS eff_ts
            FROM events WHERE COALESCE(last_seen_at, created_at) >= $1
              AND centroid IS NOT NULL
            ORDER BY COALESCE(last_seen_at, created_at) DESC LIMIT 200""",
            since,
        )
        print(f'  Events in time window ({len(events)}):')
        for e in events:
            print(f'    id={e["id"][:12]} title={e["canonical_title"][:50]} eff_ts={e["eff_ts"]}')
    finally:
        await conn.close()

    result2 = await cluster_batch(db_url, batch_size=50)
    print(f'  R2 result: {result2}')

asyncio.run(main())