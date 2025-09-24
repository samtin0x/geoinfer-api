from typing import Any, Tuple

from fastapi import Request
import redis.asyncio as redis


def extract_request_and_redis(
    *args: Any, **kwargs: Any
) -> Tuple[Request | None, redis.Redis | None]:
    """Extract Request and redis.Redis from endpoint args/kwargs."""
    request: Request | None = None
    redis_client: redis.Redis | None = None

    for arg in args:
        if isinstance(arg, Request):
            request = arg
            break

    if not request:
        maybe_request = kwargs.get("request")
        if isinstance(maybe_request, Request):
            request = maybe_request

    for arg in args:
        if isinstance(arg, redis.Redis):
            redis_client = arg
            break

    if not redis_client:
        maybe_redis = kwargs.get("redis_client")
        if isinstance(maybe_redis, redis.Redis):
            redis_client = maybe_redis

    return request, redis_client
