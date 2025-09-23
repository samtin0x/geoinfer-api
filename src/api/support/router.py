from fastapi import APIRouter, Request

from src.api.core.dependencies import AsyncSessionDep, CurrentUserAuthDep
from src.api.core.messages import APIResponse, MessageCode
from .handler import clear_current_user_organization_caches

router = APIRouter(prefix="/support", tags=["support"])


@router.post("/cache/clear", response_model=APIResponse[bool])
async def clear_cache_endpoint(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> APIResponse[bool]:
    """
    Clear Redis caches for the current user and organization."""
    success = await clear_current_user_organization_caches(
        current_user.user.id, current_user.organization.id
    )

    return APIResponse.success(message_code=MessageCode.SUCCESS, data=success)
