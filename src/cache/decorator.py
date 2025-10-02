import pickle
import redis.asyncio as redis
from functools import wraps
from uuid import UUID

from src.utils.logger import get_logger
from src.utils.settings.redis import RedisSettings

logger = get_logger(__name__)


def _generate_cache_key(func, args: tuple, kwargs: dict) -> str:
    """Generate cache key from function name and business parameters only."""
    key_parts = [func.__module__.replace(".", ":"), func.__qualname__.replace(".", ":")]

    # Skip 'self' for instance methods
    start_idx = 1 if args and hasattr(args[0], "__class__") else 0

    # Only include simple types in cache key (skip Request, AsyncSession, etc.)
    for arg in args[start_idx:]:
        if isinstance(arg, (str, int, float, bool, UUID)):
            safe_arg = str(arg).replace(":", "_").replace("*", "_")
            key_parts.append(safe_arg)

    # Include kwargs that are simple types
    for k, v in sorted(kwargs.items()):
        if isinstance(v, (str, int, float, bool, UUID)):
            safe_val = str(v).replace(":", "_").replace("*", "_")
            key_parts.append(f"{k}={safe_val}")

    return "cache:" + ":".join(key_parts)


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


async def _set_cache(key: str, value, ttl: int, tags: list[str] | None = None) -> bool:
    """Set value in Redis cache with TTL and optional tags."""
    try:
        redis_client = redis.from_url(RedisSettings().REDIS_URL, decode_responses=False)
        pickled_value = pickle.dumps(value)
        await redis_client.setex(key, ttl, pickled_value)

        # Extract additional tags from the cached value if it's an AuthenticatedUserContext
        result_tags = _extract_tags_from_result(value)
        all_tags = list(set((tags or []) + result_tags))

        # Track cache key by tags for easy invalidation
        if all_tags:
            for tag in all_tags:
                tag_key = f"cache:tag:{tag}"
                await redis_client.sadd(tag_key, key)
                await redis_client.expire(tag_key, ttl)

        await redis_client.close()
        return True
    except Exception as e:
        logger.error(f"Failed to set cache key '{key}': {e}")
        return False


def _extract_tags(args: tuple, kwargs: dict) -> list[str]:
    """Extract UUIDs from args/kwargs for cache tagging."""
    tags = []
    start_idx = 1 if args and hasattr(args[0], "__class__") else 0

    # Tag all UUIDs found in arguments
    for arg in args[start_idx:]:
        if isinstance(arg, UUID):
            tags.extend([f"user:{arg}", f"org:{arg}"])

    for k, v in kwargs.items():
        if isinstance(v, UUID):
            if "user" in k.lower():
                tags.append(f"user:{v}")
            elif "org" in k.lower():
                tags.append(f"org:{v}")

    return tags


def _extract_tags_from_result(value) -> list[str]:
    """Extract tags from cached result values (e.g., AuthenticatedUserContext)."""
    tags = []

    # Handle AuthenticatedUserContext
    if hasattr(value, "user") and hasattr(value, "organization"):
        if hasattr(value.user, "id"):
            tags.append(f"user:{value.user.id}")
        if hasattr(value.organization, "id"):
            tags.append(f"org:{value.organization.id}")

    return tags


def cached(ttl: int = 900):
    """Cache decorator with Redis backend."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = _generate_cache_key(func, args, kwargs)

            # Try cache first
            cached_value = await _get_cache(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit: {cache_key}")
                return cached_value

            # Execute function
            result = await func(*args, **kwargs)

            # Cache with tags for invalidation
            tags = _extract_tags(args, kwargs)
            await _set_cache(cache_key, result, ttl, tags)

            logger.debug(f"Cached: {cache_key}")
            return result

        return wrapper

    return decorator


async def invalidate_cache(func, *args, **kwargs) -> bool:
    """Invalidate cache entry for a specific function call."""
    try:
        cache_key = _generate_cache_key(func, args, kwargs)
        redis_client = redis.from_url(RedisSettings().REDIS_URL, decode_responses=False)

        result = await redis_client.delete(cache_key)

        # Clean up tag references
        tags = _extract_tags(args, kwargs)
        if tags:
            for tag in tags:
                tag_key = f"cache:tag:{tag}"
                await redis_client.srem(tag_key, cache_key)

        await redis_client.close()

        if result:
            logger.info(f"Invalidated cache: {cache_key}")
        return result > 0
    except Exception as e:
        logger.error(f"Failed to invalidate cache for {func.__name__}: {e}")
        return False


async def _invalidate_by_tag(tag: str) -> int:
    """Invalidate all cache entries with a specific tag."""
    try:
        redis_client = redis.from_url(RedisSettings().REDIS_URL, decode_responses=True)

        tag_key = f"cache:tag:{tag}"
        cache_keys = await redis_client.smembers(tag_key)

        if not cache_keys:
            await redis_client.close()
            return 0

        deleted = await redis_client.delete(*cache_keys, tag_key)
        await redis_client.close()

        logger.info(f"Invalidated {len(cache_keys)} entries for {tag}")
        return deleted

    except Exception as e:
        logger.error(f"Failed to invalidate tag '{tag}': {e}")
        return 0


async def _invalidate_cache_pattern(pattern: str) -> int:
    """
    Internal helper to invalidate cache entries matching a pattern.

    Note: This is a fallback for backward compatibility. Prefer using tag-based
    invalidation (_invalidate_by_tag) for better performance.
    """
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
            logger.debug(f"No cache entries found matching pattern '{pattern}'")
            deleted_count = 0

        await redis_client.close()
        return deleted_count

    except Exception as e:
        logger.error(f"Failed to invalidate cache pattern '{pattern}': {e}")
        return 0


async def invalidate_user_cache(user_id: UUID) -> int:
    """Invalidate all cache entries for a specific user."""
    count = await _invalidate_by_tag(f"user:{user_id}")
    logger.info(f"Invalidated {count} cache entries for user {user_id}")
    return count


async def invalidate_organization_cache(organization_id: UUID) -> int:
    """Invalidate all cache entries for a specific organization."""
    count = await _invalidate_by_tag(f"org:{organization_id}")
    logger.info(f"Invalidated {count} cache entries for organization {organization_id}")
    return count


async def invalidate_entity_cache(entity_id: UUID) -> int:
    """Invalidate all cache entries for a specific entity (generic)."""
    count = await _invalidate_by_tag(f"entity:{entity_id}")
    logger.info(f"Invalidated {count} cache entries for entity {entity_id}")
    return count


async def invalidate_api_key_cache(api_key: str):
    """Invalidate cache for a specific API key."""
    await _invalidate_cache_pattern(f"cache:*{api_key}*")
    logger.info("Invalidated cache for API key")


# Backward compatibility aliases
async def invalidate_user_auth_cache(user_id: UUID):
    """Invalidate all auth cache for a specific user."""
    return await invalidate_user_cache(user_id)


async def invalidate_onboarding_cache(user_id: UUID):
    """Invalidate onboarding cache for a specific user."""
    return await invalidate_user_cache(user_id)


async def invalidate_user_roles_cache(user_id: UUID, organization_id: UUID):
    """Invalidate user roles cache for a specific user and organization."""
    user_count = await invalidate_user_cache(user_id)
    org_count = await invalidate_organization_cache(organization_id)
    logger.info(
        f"Invalidated {user_count + org_count} cache entries for user {user_id} in organization {organization_id}"
    )


async def invalidate_user_permissions_cache(user_id: UUID, organization_id: UUID):
    """Invalidate user permissions cache for a specific user and organization."""
    user_count = await invalidate_user_cache(user_id)
    org_count = await invalidate_organization_cache(organization_id)
    logger.info(
        f"Invalidated {user_count + org_count} cache entries for user {user_id} in organization {organization_id}"
    )


async def invalidate_user_organization_cache(user_id: UUID):
    """Invalidate user organization cache for a specific user."""
    return await invalidate_user_cache(user_id)


async def invalidate_plan_tier_cache(user_id: UUID, organization_id: UUID):
    """Invalidate all caches for a user and organization."""
    logger.info(f"Clearing caches for user {user_id}, org {organization_id}")
    await invalidate_user_cache(user_id)
    await invalidate_organization_cache(organization_id)
    logger.info("Cache invalidation complete")
