"""
pt-media-os — Database Connection Pool

Provides an asyncpg connection pool singleton for all services.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

from ai.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the global asyncpg connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        logger.info("Database connection pool created (max_size=10)")
    return _pool


async def close_pool() -> None:
    """Close the connection pool. Call on shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed")


async def fetch_one(query: str, *args: Any) -> asyncpg.Record | None:
    """Execute a query and return the first row."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetch_all(query: str, *args: Any) -> list[asyncpg.Record]:
    """Execute a query and return all rows."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def execute(query: str, *args: Any) -> str:
    """Execute a query (INSERT/UPDATE/DELETE) and return the status."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)


async def execute_many(query: str, args_list: list[tuple]) -> None:
    """Execute a query with many parameter sets in a transaction."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(query, args_list)
