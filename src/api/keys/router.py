from uuid import UUID
from fastapi import APIRouter, Request

from src.api.core.dependencies import (
    AsyncSessionDep,
    CurrentUserAuthDep,
)
from src.api.core.decorators.auth import require_permission, require_plan_tier
from src.database.models.organizations import OrganizationPermission, PlanTier
from src.utils.logger import get_logger
from src.api.keys.schemas import (
    KeyModel,
    KeyWithSecret,
    KeyCreateRequest,
    KeyCreateResponse,
    KeyListResponse,
    KeyDeleteResponse,
)
from src.api.core.messages import APIResponse, MessageCode
from src.api.core.exceptions.base import GeoInferException
from src.modules.keys.api_keys import ApiKeyManagementService
from fastapi import status

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
    service = ApiKeyManagementService(db)
    api_key, plain_key = await service.create_api_key(
        organization_id=current_user.organization.id,
        user_id=current_user.user.id,
        name=key_data.name,
    )
    key_with_secret = KeyWithSecret(
        **KeyModel.model_validate(api_key).model_dump(), key=plain_key
    )
    return APIResponse.success(
        message_code=MessageCode.API_KEY_CREATED, data=key_with_secret
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
    service = ApiKeyManagementService(db)
    api_key, plain_key = await service.regenerate_api_key(
        key_id, current_user.organization.id
    )
    key_with_secret = KeyWithSecret(
        **KeyModel.model_validate(api_key).model_dump(), key=plain_key
    )
    return APIResponse.success(
        message_code=MessageCode.API_KEY_CREATED, data=key_with_secret
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
    service = ApiKeyManagementService(db)
    keys = await service.list_organization_api_keys(current_user.organization.id)
    key_list = [KeyModel.model_validate(key) for key in keys]
    return APIResponse.success(data={"keys": key_list, "total": len(key_list)})


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
    service = ApiKeyManagementService(db)
    success = await service.delete_api_key(key_id, current_user.organization.id)
    if not success:
        raise GeoInferException(
            MessageCode.API_KEY_NOT_FOUND,
            status.HTTP_404_NOT_FOUND,
            {"description": f"API key {key_id} not found or access denied"},
        )
    return APIResponse.success(
        message_code=MessageCode.API_KEY_DELETED, data={"deleted": True}
    )
