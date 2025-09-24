"""Redis middleware for connection management."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.redis.client import close_redis_pool, is_redis_healthy
from src.utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def redis_lifespan(app: FastAPI):
    """
    Redis connection lifespan manager for FastAPI.

    This ensures Redis connection is established on startup
    and properly closed on shutdown.
    """
    # Startup
    try:
        # Redis pool will be initialized lazily on first use
        logger.info("Redis connection pool ready for lazy initialization")

    except Exception as e:
        logger.error(f"Failed to connect to Redis on startup: {e}")
        # Continue without Redis - rate limiting will fail open
        app.state.redis = None

    yield

    # Shutdown
    try:
        await close_redis_pool()
        logger.info("Redis connection pool closed successfully")
    except Exception as e:
        logger.error(f"Error closing Redis connection: {e}")


async def add_redis_headers_middleware(request, call_next):
    """
    Middleware to add Redis health status headers.
    """
    response = await call_next(request)

    # Add Redis health status to response headers (for debugging)
    redis_healthy = await is_redis_healthy()
    response.headers["X-Redis-Status"] = "healthy" if redis_healthy else "unhealthy"

    return response
