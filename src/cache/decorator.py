import hashlib
import pickle
import redis.asyncio as redis
from functools import wraps
from uuid import UUID

from src.utils.logger import get_logger
from src.utils.settings.redis import RedisSettings

logger = get_logger(__name__)


def _generate_cache_key(func, args: tuple, kwargs: dict) -> str:
    """Generate a consistent cache key for the function call."""
    # Create a hash of the function name and arguments
    key_parts = [func.__module__, func.__qualname__]

    # Skip 'self' for instance methods (first argument)
    # Check if this looks like an instance method by checking if first arg is an object
    start_idx = 0
    if (
        args
        and hasattr(args[0], "__dict__")
        and not isinstance(args[0], (str, int, float, bool, list, dict, tuple, set))
    ):
        start_idx = 1

    # Add positional arguments (skipping self if instance method)
    for arg in args[start_idx:]:
        key_parts.append(str(arg))

    # Add keyword arguments in sorted order
    for k, v in sorted(kwargs.items()):
        key_parts.append(f"{k}:{v}")

    key_string = "|".join(key_parts)
    return f"cache:{hashlib.md5(key_string.encode()).hexdigest()}"


async def _get_cache(key: str):
    """Get value from Redis cache."""
    try:
        redis_client = redis.from_url(RedisSettings().REDIS_URL, decode_responses=False)
        value = await redis_client.get(key)
        await redis_client.close()

        if value is not None:
            return pickle.loads(value)
        return None
    except Exception as e:
        logger.error(f"Failed to get cache key '{key}': {e}")
        return None


async def _set_cache(key: str, value, ttl: int) -> bool:
    """Set value in Redis cache with TTL."""
    try:
        redis_client = redis.from_url(RedisSettings().REDIS_URL, decode_responses=False)
        pickled_value = pickle.dumps(value)
        result = await redis_client.setex(key, ttl, pickled_value)
        await redis_client.close()
        return result
    except Exception as e:
        logger.error(f"Failed to set cache key '{key}': {e}")
        return False


def cached(ttl: int = 900):
    """
    Cache decorator with custom TTL using Redis backend.

    Args:
        ttl: Time to live in seconds (default: 900 = 15 minutes)

    Usage:
        @cached()              # 15 minutes (default)
        @cached(60)            # 1 minute
        @cached(300)           # 5 minutes
        @cached(3600)          # 1 hour
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = _generate_cache_key(func, args, kwargs)

            # Try to get from cache first
            cached_value = await _get_cache(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit for {func.__name__}")
                return cached_value

            logger.debug(f"Cache miss for {func.__name__}")

            # Execute the function
            result = await func(*args, **kwargs)

            # Cache the result
            await _set_cache(cache_key, result, ttl)

            logger.debug(f"Cached result for {func.__name__}")
            return result

        return wrapper

    return decorator


async def invalidate_cache(func, *args, **kwargs) -> bool:
    """Invalidate cache entry for a specific function call."""
    try:
        cache_key = _generate_cache_key(func, args, kwargs)
        redis_client = redis.from_url(RedisSettings().REDIS_URL, decode_responses=False)

        result = await redis_client.delete(cache_key)
        await redis_client.close()

        if result:
            logger.info(
                f"Invalidated cache for {func.__name__} with args={args}, kwargs={kwargs}"
            )
        else:
            logger.debug(f"No cache entry found for {func.__name__}")

        return result > 0
    except Exception as e:
        logger.error(f"Failed to invalidate cache for {func.__name__}: {e}")
        return False


async def _invalidate_cache_pattern(pattern: str):
    """Internal helper to invalidate cache entries matching a pattern."""
    try:
        redis_client = redis.from_url(RedisSettings().REDIS_URL, decode_responses=True)

        # Find keys matching the pattern
        keys = await redis_client.keys(pattern)
        if keys:
            deleted_count = await redis_client.delete(*keys)
            logger.info(
                f"Invalidated {deleted_count} cache entries matching '{pattern}'"
            )
        else:
            logger.info(f"No cache entries found matching pattern '{pattern}'")

        await redis_client.close()

    except Exception as e:
        logger.error(f"Failed to invalidate cache pattern '{pattern}': {e}")


async def invalidate_user_auth_cache(user_id: UUID):
    """Invalidate all auth cache for a specific user."""
    await _invalidate_cache_pattern(f"cache:*{user_id}*")
    logger.info(f"Invalidated auth cache for user {user_id}")


async def invalidate_organization_cache(organization_id: UUID):
    """Invalidate all cache for a specific organization."""
    await _invalidate_cache_pattern(f"cache:*{organization_id}*")
    logger.info(f"Invalidated cache for organization {organization_id}")


async def invalidate_api_key_cache(api_key: str):
    """Invalidate cache for a specific API key."""
    await _invalidate_cache_pattern(f"cache:*{api_key}*")
    logger.info("Invalidated cache for API key")


async def invalidate_onboarding_cache(user_id: UUID):
    """Invalidate onboarding cache for a specific user."""
    await _invalidate_cache_pattern(f"cache:*ensure_user_onboarded_cached*{user_id}*")
    logger.info(f"Invalidated onboarding cache for user {user_id}")


async def invalidate_user_roles_cache(user_id: UUID, organization_id: UUID):
    """Invalidate user roles cache for a specific user and organization."""
    await _invalidate_cache_pattern(f"cache:*{user_id}*roles*{organization_id}*")
    logger.info(
        f"Invalidated roles cache for user {user_id} in organization {organization_id}"
    )


async def invalidate_user_permissions_cache(user_id: UUID, organization_id: UUID):
    """Invalidate user permissions cache for a specific user and organization."""
    await _invalidate_cache_pattern(f"cache:*{user_id}*permissions*{organization_id}*")
    logger.info(
        f"Invalidated permissions cache for user {user_id} in organization {organization_id}"
    )


async def invalidate_user_organization_cache(user_id: UUID):
    """Invalidate user organization cache for a specific user."""
    # We need to get a reference to the actual service methods to invalidate
    # For now, use pattern-based invalidation
    await _invalidate_cache_pattern(f"cache:*user_org_id:{user_id}*")
    await _invalidate_cache_pattern(f"cache:*user_org_data:{user_id}*")
    logger.info(f"Invalidated organization cache for user {user_id}")


async def invalidate_plan_tier_cache(user_id: UUID, organization_id: UUID):
    """Invalidate all caches that might be affected by a plan tier change."""
    logger.info(
        f"Invalidating all caches for plan tier change: user {user_id}, org {organization_id}"
    )

    # Clear user-specific caches
    await invalidate_user_auth_cache(user_id)
    await invalidate_onboarding_cache(user_id)
    await invalidate_user_organization_cache(user_id)
    await invalidate_organization_cache(organization_id)

    # Clear role and permission caches
    await invalidate_user_roles_cache(user_id, organization_id)
    await invalidate_user_permissions_cache(user_id, organization_id)

    # Clear any plan-tier specific caches
    await _invalidate_cache_pattern(f"cache:*{user_id}*plan*")
    await _invalidate_cache_pattern(f"cache:*{organization_id}*plan*")

    # Clear any auth-related caches that might include plan tier info
    await _invalidate_cache_pattern(f"cache:*{user_id}*auth*")
    await _invalidate_cache_pattern(f"cache:*{organization_id}*auth*")

    # Clear API key caches that might be affected
    await _invalidate_cache_pattern(f"cache:*{user_id}*api_key*")
    await _invalidate_cache_pattern(f"cache:*{organization_id}*api_key*")

    logger.info("Completed comprehensive cache invalidation for plan tier change")
