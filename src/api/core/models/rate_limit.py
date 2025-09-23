"""Rate limiting types and models."""

from enum import Enum

from pydantic import BaseModel


class RateLimitClientType(str, Enum):
    """Types of clients for rate limiting."""

    USER = "user"
    API_KEY = "api_key"
    TRIAL = "trial"
    IP = "ip"


# Rate limiting is now based on client type, not scope
# Cache keys: rate_limit:{client_type}:{identifier}
# Examples:
# - rate_limit:user:123
# - rate_limit:api_key:abc
# - rate_limit:trial:1.2.3.4
# - rate_limit:ip:1.2.3.4


class ClientIdentifier(BaseModel):
    """Client identifier for rate limiting."""

    client_type: RateLimitClientType
    client_id: str | None = None  # Will be set by create_rate_limit_key

    def to_cache_key(self) -> str:
        """Generate Redis cache key for this client."""
        if self.client_type == RateLimitClientType.USER:
            return f"rate_limit:user:{self.client_id}"
        elif self.client_type == RateLimitClientType.API_KEY:
            return f"rate_limit:api_key:{self.client_id}"
        elif self.client_type == RateLimitClientType.IP:
            return f"rate_limit:ip:{self.client_id}"
        else:  # TRIAL
            return f"rate_limit:trial:{self.client_id}"

    def __str__(self) -> str:
        """String representation for logging."""
        if self.client_type == RateLimitClientType.USER:
            return f"user:{self.client_id}"
        elif self.client_type == RateLimitClientType.API_KEY:
            return f"api_key:{self.client_id}"
        elif self.client_type == RateLimitClientType.IP:
            return f"ip:{self.client_id}"
        else:  # TRIAL
            return f"trial:{self.client_id}"


class RateLimitResult(BaseModel):
    """Result of rate limit check."""

    is_allowed: bool
    current_count: int
    time_to_reset: int | None
    client_identifier: "ClientIdentifier"
    limit: int
    window_seconds: int


class RateLimitConfig(BaseModel):
    """Configuration for rate limiting."""

    limit: int
    window_seconds: int
    client_type: RateLimitClientType
