"""Async Redis client utilities and lifespan management."""

from contextlib import asynccontextmanager

import redis.asyncio as redis

from src.utils.settings.redis import RedisSettings
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Global connection pool - initialized once, reused everywhere
_redis_pool: redis.ConnectionPool | None = None


async def _ensure_redis_pool() -> redis.ConnectionPool:
    """Ensure Redis connection pool is initialized."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.ConnectionPool.from_url(
            RedisSettings().REDIS_URL, decode_responses=True
        )
    return _redis_pool


async def get_redis_client() -> redis.Redis:
    """Get Redis client for dependency injection and direct usage."""
    pool = await _ensure_redis_pool()
    return redis.Redis(connection_pool=pool)


async def close_redis_pool() -> None:
    """Close Redis connection pool - called during app shutdown."""
    global _redis_pool
    if _redis_pool:
        await _redis_pool.disconnect()
        _redis_pool = None


async def is_redis_healthy() -> bool:
    """Check if Redis connection is healthy."""
    try:
        client = await get_redis_client()
        await client.ping()
        return True
    except Exception:
        return False


@asynccontextmanager
async def redis_lifespan(app):
    """Compose-able lifespan context to close Redis pool on shutdown."""
    try:
        yield
    finally:
        await close_redis_pool()
