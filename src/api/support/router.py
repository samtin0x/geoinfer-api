from fastapi import APIRouter, Request

from src.api.core.dependencies import AsyncSessionDep, CurrentUserAuthDep
from src.api.core.messages import APIResponse, MessageCode
from src.cache.decorator import invalidate_plan_tier_cache

router = APIRouter(prefix="/support", tags=["support"])


@router.post("/cache/clear", response_model=APIResponse[bool])
async def clear_cache_endpoint(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> APIResponse[bool]:
    """
    Clear Redis caches for the current user and organization."""
    try:
        await invalidate_plan_tier_cache(
            current_user.user.id, current_user.organization.id
        )
        success = True
    except Exception:
        success = False

    return APIResponse.success(message_code=MessageCode.SUCCESS, data=success)
