"""Rate limiting middleware for FastAPI."""

from fastapi import Request, status
from fastapi.responses import JSONResponse

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.api.core.models.rate_limit import (
    ClientIdentifier,
    RateLimitClientType,
)
from src.services.auth.rate_limiting import RateLimiter
from src.services.redis_service import get_redis_client
from src.utils.logger import get_logger

logger = get_logger(__name__)


class RateLimitMiddleware:
    """Rate limiting middleware with configurable limits per endpoint."""

    def __init__(self, app) -> None:
        self.app = app
        self.rate_limiters: dict[str, RateLimiter] = {}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        # Check if this endpoint needs rate limiting
        rate_limit_config = request.state.rate_limit_config

        if rate_limit_config:
            try:
                await self._check_rate_limit(request, rate_limit_config)
            except GeoInferException as e:
                response = JSONResponse(
                    status_code=e.status_code,
                    content=e.to_response_dict(),
                    headers={
                        "Retry-After": str(rate_limit_config.get("retry_after", 60))
                    },
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)

    async def _check_rate_limit(self, request: Request, config: dict) -> None:
        """Check rate limit for the request."""
        # Get client identifier
        client_id = await self._get_client_id(request, config)

        # Get or create rate limiter for this endpoint
        endpoint_key = f"{request.method}:{request.url.path}"
        if endpoint_key not in self.rate_limiters:
            redis_client = await get_redis_client()
            self.rate_limiters[endpoint_key] = RateLimiter(redis_client)

        rate_limiter = self.rate_limiters[endpoint_key]

        # Create client identifier for rate limiting
        # For middleware, we use a simple approach since we don't have access to the user plan tier
        client_identifier = ClientIdentifier(
            client_type=RateLimitClientType.IP,  # Default fallback
            client_id=client_id,
        )

        # Check rate limit
        result = await rate_limiter.is_allowed(
            client_identifier, config["limit"], config["window_seconds"]
        )

        if not result.is_allowed:
            current_count = result.current_count
            time_to_reset = result.time_to_reset
            logger.warning(
                f"Rate limit exceeded for {client_id} on {endpoint_key}: "
                f"{current_count}/{config['limit']} in {config['window_seconds']}s"
            )

            # Add rate limit info to config for response headers
            config["retry_after"] = result.time_to_reset or config["window_seconds"]

            # Set rate limit headers for the response
            config["rate_limit_headers"] = {
                "X-RateLimit-Limit": str(config["limit"]),
                "X-RateLimit-Remaining": "0",  # No remaining requests
                "X-RateLimit-Reset": str(
                    result.time_to_reset or config["window_seconds"]
                ),
                "X-RateLimit-Retry-After": str(config["retry_after"]),
                "X-RateLimit-Window": str(config["window_seconds"]),
            }

            raise GeoInferException(
                MessageCode.RATE_LIMIT_EXCEEDED,
                status.HTTP_429_TOO_MANY_REQUESTS,
                details={
                    "limit": config["limit"],
                    "window_seconds": config["window_seconds"],
                    "current_count": current_count,
                    "retry_after": time_to_reset,
                },
                headers=config.get("rate_limit_headers", {}),
            )

    async def _get_client_id(self, request: Request, config: dict) -> str:
        """Get client identifier for rate limiting."""
        # Priority: API Key > User ID > IP Address

        # Try API key first
        api_key = request.state.api_key
        if api_key and hasattr(api_key, "id"):
            return f"api_key:{api_key.id}"

        # Try user ID
        user = request.state.user
        if user and hasattr(user, "id"):
            return f"user:{user.id}"

        # Fallback to IP address
        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        return f"ip:{client_ip}"


def rate_limit(limit: int, window_seconds: int, per: str = "endpoint"):
    """
    Decorator to add rate limiting to FastAPI endpoints.

    Args:
        limit: Maximum number of requests allowed
        window_seconds: Time window in seconds
        per: Rate limit scope ("endpoint", "user", "ip")
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Get request from function arguments
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            if not request:
                # Try to get from kwargs
                request = kwargs.get("request")

            if request:
                # Set rate limit config on request state
                request.state.rate_limit_config = {
                    "limit": limit,
                    "window_seconds": window_seconds,
                    "per": per,
                }

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def production_rate_limit(limit: int = 100, window_seconds: int = 3600):
    """Rate limit decorator for production endpoints (default: 100 requests/hour)."""
    return rate_limit(limit, window_seconds, "endpoint")


def burst_rate_limit(limit: int = 10, window_seconds: int = 60):
    """Rate limit decorator for burst protection (default: 10 requests/minute)."""
    return rate_limit(limit, window_seconds, "endpoint")


def trial_rate_limit(limit: int = 3, window_seconds: int = 86400):
    """Rate limit decorator for trial endpoints (default: 3 requests/day)."""
    return rate_limit(limit, window_seconds, "ip")
