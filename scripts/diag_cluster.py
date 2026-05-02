#!/usr/bin/env python3
"""Diagnose why clustering test fails: events_created=0 despite processed>=1."""
import asyncio, os, uuid, datetime as _dt
import asyncpg
from dotenv import load_dotenv
from openai import AsyncOpenAI
from services.clustering.clusterer import cluster_batch

async def main():
    load_dotenv()
    db_url = os.getenv('DATABASE_URL', '')
    conn = await asyncpg.connect(db_url)
    try:
        outlet = await conn.fetchrow('SELECT id::text FROM outlets LIMIT 1')
        uid = uuid.uuid4().hex[:8]
        topic_tag = uuid.uuid4().hex
        old_time = _dt.datetime.now(tz=_dt.timezone.utc) - _dt.timedelta(days=730)
        text = (
            f'Descoberta arqueológica única no vale do Côa revela pinturas '
            f'rupestres com mais de trinta mil anos. {topic_tag}'
        )
        await conn.execute(
            """INSERT INTO articles (
                outlet_id, canonical_url, url_hash, content_hash,
                title, cleaned_text, language, word_count, status, published_at, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, 'pt', $7, 'pending', $8, $8)
            ON CONFLICT (canonical_url) DO UPDATE
            SET status = 'pending', published_at = $8, created_at = $8""",
            outlet['id'], f'https://diag.test.com/{uid}', f'hash-{uid}', f'ch-{uid}',
            f'Test diagnostic [{uid}]', text, len(text.split()), old_time,
        )
        client = AsyncOpenAI(
            base_url=f"{os.getenv('OLLAMA_HOST', 'http://localhost:11434')}/v1",
            api_key='ollama',
        )
        resp = await client.embeddings.create(model='nomic-embed-text', input=[f'search_document: {text}'])
        emb = resp.data[0].embedding
        await conn.execute(
            """UPDATE articles SET embedding = $1::vector, status = 'embedded' WHERE canonical_url = $2""",
            str(emb), f'https://diag.test.com/{uid}',
        )
    finally:
        await conn.close()

    result = await cluster_batch(db_url, batch_size=50)
    print(f'RESULT: {result}')

    #go Check what's in the DB
    conn2 = await asyncpg.connect(db_url)
    try:
        articles = await conn2.fetch('SELECT id, status, embedding IS NOT NULL as has_emb FROM articles')
        print(f'Articles in DB: {len(articles)}')
        for a in articles:
            print(f'  {a["id"][:8]}... status={a["status"]} has_emb={a["has_emb"]}')
        events = await conn2.fetch('SELECT id, canonical_title, status FROM events')
        print(f'Events in DB: {len(events)}')
        for e in events:
            print(f'  {e["id"][:8]}... title={e["canonical_title"][:50]} status={e["status"]}')
        eas = await conn2.fetch('SELECT * FROM event_articles')
        print(f'Event_articles rows: {len(eas)}')
    finally:
        await conn2.close()

asyncio.run(main())