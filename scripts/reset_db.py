#!/usr/bin/env python3
"""Reset the database by truncating all data tables (preserves schema + seed data like outlets/owners)."""
import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

TABLES = [
    "ai_runs",
    "event_summaries",
    "event_scores",
    "event_documents",
    "event_articles",
    "undercoverage_flags",
    "article_entities",
    "article_analysis",
    "claims",
    "entities",
    "articles",
    "events",
    "raw_items",
    "source_documents",
    "daily_digests",
]


async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await conn.execute(f"TRUNCATE TABLE {', '.join(TABLES)} CASCADE")
        # Verify
        for table in TABLES:
            row = await conn.fetchrow(f"SELECT count(*) as cnt FROM {table}")
            print(f"  {table}: {row['cnt']} rows")
        print("\n✓ Database reset complete")
    finally:
        await conn.close()


asyncio.run(main())