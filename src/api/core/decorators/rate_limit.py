from functools import wraps
from typing import Any, Callable

from fastapi import Request, status
import redis.asyncio as redis

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.api.core.models.rate_limit import (
    ClientIdentifier,
    RateLimitClientType,
)
from src.services.auth.rate_limiting import RateLimiter
from src.utils.logger import get_logger


logger = get_logger(__name__)


def get_client_ip(request: Request) -> str:
    """Extract client IP from request, handling proxies."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    if request.client:
        return request.client.host

    return "unknown"


def create_rate_limit_key(request: Request) -> ClientIdentifier:
    """
    Create rate limit client identifier.

    Priority order:
    1. API Key (highest priority)
    2. User ID
    3. Trial IP (for trial endpoints)
    4. Regular IP Address (fallback)

    Args:
        request: FastAPI request object

    Returns:
        ClientIdentifier with proper typing
    """
    # Try API key first (highest priority)
    api_key = request.state.api_key
    if api_key and hasattr(api_key, "id"):
        return ClientIdentifier(
            client_type=RateLimitClientType.API_KEY,
            client_id=str(api_key.id),
        )

    # Try user ID
    user = request.state.user
    if user and hasattr(user, "id"):
        return ClientIdentifier(
            client_type=RateLimitClientType.USER,
            client_id=str(user.id),
        )

    # Check if this is a trial endpoint (no auth required)
    # Trial endpoints are identified by having no user/api_key in request.state
    # and being a POST request to /prediction/trial
    if (
        request.method == "POST"
        and request.url.path.endswith("/trial")
        and not request.state.user
        and not request.state.api_key
    ):
        ip_address = get_client_ip(request)
        return ClientIdentifier(
            client_type=RateLimitClientType.TRIAL,
            client_id=ip_address,
        )

    # Fallback to IP address
    ip_address = get_client_ip(request)
    return ClientIdentifier(
        client_type=RateLimitClientType.IP,
        client_id=ip_address,
    )


def rate_limit(
    limit: int,
    window_seconds: int,
):
    """
    Rate limiting decorator for FastAPI endpoints.

    Args:
        limit: Maximum requests allowed
        window_seconds: Time window in seconds
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract request and redis client from dependencies
            request: Request | None = None
            redis_client: redis.Redis | None = None

            # Find request in args/kwargs
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                request = kwargs.get("request")

            # Find redis client in args/kwargs
            for arg in args:
                if isinstance(arg, redis.Redis):
                    redis_client = arg
                    break
            if not redis_client:
                redis_client = kwargs.get("redis_client")

            if not request:
                logger.error("Rate limit decorator: Request not found")
                return await func(*args, **kwargs)

            if not redis_client:
                logger.warning(
                    "Rate limit decorator: Redis client not found, skipping rate limit"
                )
                return await func(*args, **kwargs)

            # Check rate limit using typed client identification
            await check_rate_limit(request, redis_client, limit, window_seconds)

            return await func(*args, **kwargs)

        return wrapper

    return decorator


async def check_rate_limit(
    request: Request,
    redis_client: redis.Redis,
    limit: int,
    window_seconds: int,
) -> None:
    """
    Check rate limit for endpoint.

    Args:
        request: FastAPI request object
        redis_client: Redis client for rate limiting
        limit: Maximum requests allowed
        window_seconds: Time window in seconds

    Raises:
        GeoInferException: When rate limit is exceeded
    """
    # Create client identifier
    client_identifier = create_rate_limit_key(request)

    # Perform rate limit check
    rate_limiter = RateLimiter(redis_client)
    result = await rate_limiter.is_allowed(client_identifier, limit, window_seconds)

    if not result.is_allowed:
        logger.warning(
            f"Rate limit exceeded for {result.client_identifier} using key {client_identifier.to_cache_key()}: "
            f"{result.current_count}/{result.limit} in {result.window_seconds}s"
        )

        raise GeoInferException(
            MessageCode.RATE_LIMIT_EXCEEDED,
            status.HTTP_429_TOO_MANY_REQUESTS,
            details={
                "limit": result.limit,
                "window_seconds": result.window_seconds,
                "current_count": result.current_count,
                "retry_after": result.time_to_reset or result.window_seconds,
                "rate_key": client_identifier.to_cache_key(),
                "client_type": result.client_identifier.client_type.value,
            },
            headers={
                "X-RateLimit-Limit": str(result.limit),
                "X-RateLimit-Reset": str(result.time_to_reset or result.window_seconds),
                "X-RateLimit-Retry-After": str(result.time_to_reset or result.window_seconds),
                "X-RateLimit-Window": str(result.window_seconds),
            },
        )
