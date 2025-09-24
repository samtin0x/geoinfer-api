import time
import uuid

import redis.asyncio as redis

from src.api.core.models.rate_limit import (
    ClientIdentifier,
    RateLimitResult,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """Rate limiter using Redis sliding window algorithm."""

    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client

    async def is_allowed(
        self, client_identifier: ClientIdentifier, limit: int, window_seconds: int
    ) -> RateLimitResult:
        """
        Check if request is allowed within rate limit.

        Args:
            client_identifier: Typed client identifier for rate limiting
            limit: Maximum requests allowed
            window_seconds: Time window in seconds

        Returns:
            RateLimitResult: Typed result with rate limit information
        """
        try:
            key = client_identifier.to_cache_key()
            current_time = int(time.time())
            window_start = current_time - window_seconds

            # Use Redis pipeline for atomic operations
            pipe = self.redis_client.pipeline()

            # Remove expired entries
            pipe.zremrangebyscore(key, 0, window_start)

            # Count current requests in window
            pipe.zcard(key)

            # Add current request with unique identifier
            # Use current_time as score and UUID as member name to ensure uniqueness
            request_id = f"req_{current_time}_{uuid.uuid4().hex}"
            pipe.zadd(key, {request_id: current_time})

            # Set expiry
            pipe.expire(key, window_seconds + 1)

            results = await pipe.execute()
            current_count = (
                results[1] + 1
            )  # zcard result + 1 for the request we just added

            is_allowed = current_count <= limit

            # Calculate time to reset
            if current_count > limit:
                # Get oldest request time
                oldest_requests = await self.redis_client.zrange(
                    key, 0, 0, withscores=True
                )
                if oldest_requests:
                    oldest_time = int(oldest_requests[0][1])
                    time_to_reset = window_seconds - (current_time - oldest_time)
                    time_to_reset = max(0, time_to_reset)
                else:
                    time_to_reset = window_seconds
            else:
                time_to_reset = None

            if not is_allowed:
                # Remove the request we just added since it's not allowed
                await self.redis_client.zrem(key, request_id)
                current_count -= 1

            return RateLimitResult(
                is_allowed=is_allowed,
                current_count=current_count,
                time_to_reset=time_to_reset,
                client_identifier=client_identifier,
                limit=limit,
                window_seconds=window_seconds,
            )

        except Exception as e:
            logger.error(f"Rate limiter error for client {client_identifier}: {e}")
            # Fail open - allow request if Redis is down
            return RateLimitResult(
                is_allowed=True,
                current_count=0,
                time_to_reset=None,
                client_identifier=client_identifier,
                limit=limit,
                window_seconds=window_seconds,
            )

    async def get_remaining(self, key: str, limit: int, window_seconds: int) -> int:
        """Get remaining requests in current window."""
        try:
            current_time = int(time.time())
            window_start = current_time - window_seconds

            # Remove expired and count current
            pipe = self.redis_client.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zcard(key)
            results = await pipe.execute()

            current_count = results[1]
            return max(0, limit - current_count)

        except Exception as e:
            logger.error(f"Error getting remaining for key {key}: {e}")
            return limit
