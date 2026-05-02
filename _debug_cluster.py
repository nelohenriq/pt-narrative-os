"""Debug: why does cluster_batch not create events?"""
import os, uuid, datetime as _dt, asyncio, asyncpg
from dotenv import load_dotenv
load_dotenv()
from openai import AsyncOpenAI
from services.clustering.clusterer import cluster_batch, _get_unclustered_articles

async def main():
    db_url = os.getenv('DATABASE_URL','')
    
    # Step 1:upsert an article into DB
    uid = uuid.uuid4().hex[:8]
    topic_tag = uuid.uuid4().hex
    old_time = _dt.datetime.now(tz=_dt.timezone.utc) - _dt.timedelta(days=730)
    text = f'Descoberta arqueológica única no vale do Côa revela pinturas rupestres. {topic_tag}'
    
    conn = await asyncpg.connect(db_url)
    outlet = await conn.fetchrow('SELECT id::text FROM outlets LIMIT 1')
    await conn.execute('''
        INSERT INTO articles (
            outlet_id, canonical_url, url_hash, content_hash,
            title, cleaned_text, language, word_count, status, published_at, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, 'pt', $7, 'pending', $8, $8)
        ON CONFLICT (canonical_url) DO UPDATE SET status='pending', published_at=$8, created_at=$8
    ''', outlet['id'], f'https://debug.test.com/{uid}', f'hash-d-{uid}', f'ch-d-{uid}',
       f'Test article {uid}', text, len(text.split()), old_time)
    
    client = AsyncOpenAI(base_url=f"{os.getenv('OLLAMA_HOST','http://localhost:11434')}/v1", api_key='ollama')
    resp = await client.embeddings.create(model='nomic-embed-text', input=[f'search_document: {text}'])
    emb = resp.data[0].embedding
    print(f'Embedding dim: {len(emb)}')
    
    await conn.execute(
        'UPDATE articles SET embedding = $1::vector, status = \'embedded\' WHERE canonical_url = $2',
        str(emb), f'https://debug.test.com/{uid}')
    
    # Verify
    row = await conn.fetchrow('SELECT id, status, embedding IS NOT NULL as has_emb FROM articles WHERE canonical_url=$1',
                               f'https://debug.test.com/{uid}')
    print(f'Article: id={row["id"]}, status={row["status"]}, has_embedding={row["has_emb"]}')
    
    # Check unclustered
    unclustered = await conn.fetch('''
        SELECT a.id::text FROM articles a
        LEFT JOIN event_articles ea ON ea.article_id = a.id
        WHERE a.status = \'embedded\' AND a.embedding IS NOT NULL AND ea.id IS NULL
    ''')
    print(f'Unclustered articles: {len(unclustered)}')
    
    await conn.close()
    
    # Step 2: run cluster_batch
    result = await cluster_batch(db_url, batch_size=50)
    print(f'\nCluster result: {result}')
    
    # Step 3: check events table
    conn = await asyncpg.connect(db_url)
    events = await conn.fetch('SELECT count(*) FROM events')
    print(f'Events in DB: {events[0][0]}')
    article_check = await conn.fetchrow(
        'SELECT ea.event_id IS NOT NULL as linked FROM articles a LEFT JOIN event_articles ea ON ea.article_id = a.id WHERE a.canonical_url=$1',
        f'https://debug.test.com/{uid}')
    print(f'Article linked:{article_check}')
    await conn.close()

asyncio.run(main())