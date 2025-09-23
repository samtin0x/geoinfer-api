from uuid import UUID
from fastapi import APIRouter, Request

from src.api.core.dependencies import (
    AsyncSessionDep,
    CurrentUserAuthDep,
)
from src.api.core.decorators.auth import require_permission, require_plan_tier
from src.database.models.organizations import OrganizationPermission, PlanTier
from src.utils.logger import get_logger
from .handler import (
    create_key_handler,
    delete_key_handler,
    list_keys_handler,
    regenerate_key_handler,
)
from .requests import (
    KeyCreateRequest,
    KeyCreateResponse,
    KeyDeleteResponse,
    KeyListResponse,
)

logger = get_logger(__name__)

# Create router with prefix
router = APIRouter(prefix="/keys", tags=["keys"])


@router.post("/", response_model=KeyCreateResponse)
@require_plan_tier([PlanTier.SUBSCRIBED, PlanTier.ENTERPRISE])
@require_permission(OrganizationPermission.MANAGE_API_KEYS)
async def create_key(
    request: Request,
    key_data: KeyCreateRequest,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> KeyCreateResponse:
    """Create a new API key for the authenticated user."""

    return await create_key_handler(
        db=db,
        key_data=key_data,
        user_id=current_user.user.id,
    )


@router.post("/{key_id}/regenerate", response_model=KeyCreateResponse)
@require_plan_tier([PlanTier.SUBSCRIBED, PlanTier.ENTERPRISE])
@require_permission(OrganizationPermission.MANAGE_API_KEYS)
async def regenerate_key(
    key_id: UUID,
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> KeyCreateResponse:
    """Regenerate an API key with a new secret."""

    return await regenerate_key_handler(
        db=db,
        key_id=key_id,
        user_id=current_user.user.id,
    )


@router.get("/", response_model=KeyListResponse)
@require_plan_tier([PlanTier.SUBSCRIBED, PlanTier.ENTERPRISE])
@require_permission(OrganizationPermission.MANAGE_API_KEYS)
async def list_keys(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> KeyListResponse:
    """List all API keys for the authenticated user."""

    return await list_keys_handler(
        db=db,
        user_id=current_user.user.id,
    )


@router.delete("/{key_id}", response_model=KeyDeleteResponse)
@require_plan_tier([PlanTier.SUBSCRIBED, PlanTier.ENTERPRISE])
@require_permission(OrganizationPermission.MANAGE_API_KEYS)
async def delete_key(
    key_id: UUID,
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> KeyDeleteResponse:
    """Delete an API key."""

    return await delete_key_handler(
        db=db,
        key_id=key_id,
        user_id=current_user.user.id,
    )
