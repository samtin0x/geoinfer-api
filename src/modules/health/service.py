import asyncio
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Literal

import redis.asyncio as redis
from src.utils.logger import get_logger
from src.api.core.constants import (
    PUBLIC_TRIAL_FREE_PREDICTIONS,
    PUBLIC_TRIAL_FREE_PREDICTIONS_WINDOW_SECONDS,
)
from src.api.core.models.rate_limit import (
    ClientIdentifier,
    RateLimitClientType,
)
from src.core.rate_limiting import RateLimiter


logger = get_logger(__name__)


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    service: str
    status: Literal["healthy", "unhealthy", "degraded"]
    connected: bool
    details: dict
    error: str | None = None


@dataclass
class OverallHealthStatus:
    """Overall health status with individual service results."""

    status: Literal["healthy", "degraded", "unhealthy"]
    services: dict[str, HealthCheckResult]
    timestamp: str


class HealthService:
    """Service for performing health checks on various system components."""

    def __init__(self, db: AsyncSession, redis: redis.Redis):
        self.db = db
        self.redis = redis

    async def check_database_health(self) -> HealthCheckResult:
        """Database connection health check."""
        try:
            # Simple query to test connection
            result = await self.db.execute(text("SELECT 1 as test"))
            test_value = result.scalar()

            return HealthCheckResult(
                service="database",
                status="healthy",
                connected=True,
                details={"test_query_result": test_value},
            )
        except Exception as e:
            logger.error(f"Database health check error: {e}")
            return HealthCheckResult(
                service="database",
                status="unhealthy",
                connected=False,
                details={},
                error=str(e),
            )

    async def check_redis_health(self) -> HealthCheckResult:
        """Redis connection and functionality health check."""
        try:
            # Test basic Redis operations using the injected redis client
            test_key = "health_check_test"

            # Test connection with ping
            await self.redis.ping()

            # Test basic operations
            await self.redis.setex(test_key, 10, "test_data")
            cached_value = await self.redis.get(test_key)
            await self.redis.delete(test_key)

            return HealthCheckResult(
                service="redis",
                status="healthy",
                connected=True,
                details={
                    "cache_test_passed": cached_value is not None,
                },
            )
        except Exception as e:
            logger.error(f"Redis health check error: {e}")
            return HealthCheckResult(
                service="redis",
                status="unhealthy",
                connected=False,
                details={},
                error=str(e),
            )

    async def check_rate_limit_health(self) -> HealthCheckResult:
        """Rate limiting functionality health check."""
        try:
            limit = PUBLIC_TRIAL_FREE_PREDICTIONS
            window_seconds = PUBLIC_TRIAL_FREE_PREDICTIONS_WINDOW_SECONDS

            rate_limiter = RateLimiter(self.redis)

            test_key = "rate_limit_test_key"

            # Create a test client identifier
            test_client = ClientIdentifier(
                client_type=RateLimitClientType.IP,
                client_id="health_check_test",
            )

            # Make multiple requests to test rate limiting
            results = []
            for i in range(limit + 1):  # Make limit + 1 requests
                result = await rate_limiter.is_allowed(
                    test_client, limit, window_seconds
                )
                results.append(
                    (result.is_allowed, result.current_count, result.time_to_reset)
                )
                await asyncio.sleep(0.01)

            # The last request should be blocked (is_allowed should be False)
            last_request_blocked = not results[-1][0]
            # All requests before limit should be allowed
            all_before_limit_allowed = all(results[i][0] for i in range(limit))

            # Health check passes if:
            # 1. Rate limiting is working (last request blocked)
            # 2. All requests before limit were allowed
            # 3. No exceptions occurred
            rate_limiting_works = last_request_blocked and all_before_limit_allowed

            return HealthCheckResult(
                service="rate_limit",
                status="healthy" if rate_limiting_works else "degraded",
                connected=True,
                details={
                    "key": test_key,
                    "limit": limit,
                    "window_seconds": window_seconds,
                    "requests_made": len(results),
                    "rate_limiting_works": rate_limiting_works,
                    "last_request_blocked": last_request_blocked,
                    "all_before_limit_allowed": all_before_limit_allowed,
                    "results": results,  # Detailed results for debugging
                },
            )
        except Exception as e:
            logger.error(f"Rate limit health check error: {e}")
            return HealthCheckResult(
                service="rate_limit",
                status="unhealthy",
                connected=False,
                details={},
                error=str(e),
            )

    async def run_all_checks(self) -> OverallHealthStatus:
        """Run all health checks in parallel and return overall status."""
        from datetime import datetime, timezone

        # Run all checks in parallel
        tasks = [
            self.check_database_health(),
            self.check_redis_health(),
            self.check_rate_limit_health(),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and determine overall status
        services = {}
        overall_status: Literal["healthy", "degraded", "unhealthy"] = "healthy"

        for result in results:
            if isinstance(result, Exception):
                # Handle exceptions from individual checks
                service_result = HealthCheckResult(
                    service=result.__class__.__name__,
                    status="unhealthy",
                    connected=False,
                    details={},
                    error=str(result),
                )
                overall_status = "unhealthy"
            elif isinstance(result, HealthCheckResult):
                service_result = result
                if service_result.status == "unhealthy":
                    overall_status = "unhealthy"
                elif (
                    service_result.status == "degraded" and overall_status == "healthy"
                ):
                    overall_status = "degraded"
            else:
                # Unexpected type, create error result
                service_result = HealthCheckResult(
                    service="unknown",
                    status="unhealthy",
                    connected=False,
                    details={},
                    error=f"Unexpected result type: {type(result)}",
                )
                overall_status = "unhealthy"

            services[service_result.service] = service_result

        return OverallHealthStatus(
            status=overall_status,
            services=services,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    async def get_service_status(self, service_name: str) -> HealthCheckResult | None:
        """Get status for a specific service."""
        status = await self.run_all_checks()
        return status.services.get(service_name)
