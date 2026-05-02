#!/usr/bin/env python3
"""Diagnose what event the article joined and why."""
import asyncio, os
import asyncpg
from dotenv import load_dotenv

async def main():
    load_dotenv()
    db_url = os.getenv('DATABASE_URL', '')
    conn = await asyncpg.connect(db_url)
    try:
        # Show how many events exist
        events = await conn.fetch('''SELECT id::text, canonical_title, status, 
            first_seen_at, last_seen_at, article_count FROM events''')
        print(f'Events in DB: {len(events)}')
        for e in events:
            print(f'  id={e["id"][:12]}... title="{e["canonical_title"][:80]}" '
                  f'status={e["status"]} first={e["first_seen_at"]} last={e["last_seen_at"]} '
                  f'n={e["article_count"]}')

        # Showembedded unclustered articles
        unclustered = await conn.fetch('''
            SELECT a.id::text, a.title, a.status, a.published_at
            FROM articles a
            LEFT JOIN event_articles ea ON ea.article_id = a.id
            WHERE a.status = 'embedded' AND a.embedding IS NOT NULL AND ea.id IS NULL
            ORDER BY a.created_at LIMIT 5
        ''')
        print(f'\nUnclustered embedded articles: {len(unclustered)}')
        for a in unclustered:
            print(f'  id={a["id"][:12]}... title={a["title"][:60]} published={a["published_at"]}')

        # Show what events have what articles
        ea_rows = await conn.fetch('''
            SELECT ea.event_id::text, a.title, a.published_at, ea.relevance_score
            FROM event_articles ea
            JOIN articles a ON a.id = ea.article_id
            ORDER BY ea.event_id, a.published_at
        ''')
        print(f'\nEvent-Article links: {len(ea_rows)}')
        by_event = {}
        for r in ea_rows:
            eid = r['event_id'][:12]
            by_event.setdefault(eid, []).append((r['title'][:60], r['relevance_score'], r['published_at']))
        for eid, arts in by_event.items():
            print(f'  Event {eid}: {len(arts)} articles')
            for title, score, pub in arts:
                print(f'    score={score:.3f} pub={pub} title={title}')

    finally:
        await conn.close()

asyncio.run(main())