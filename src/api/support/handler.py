from uuid import UUID

from src.cache.decorator import invalidate_plan_tier_cache


async def clear_current_user_organization_caches(
    user_id: UUID, organization_id: UUID
) -> bool:
    """Clear all caches for the current user and organization.

    Returns True if successful, False if any error occurs.
    """
    try:
        await invalidate_plan_tier_cache(user_id, organization_id)
        return True
    except Exception:
        return False
