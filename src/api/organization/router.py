"""Organization domain router."""

from uuid import UUID
from fastapi import APIRouter, Request

from src.api.core.decorators.auth import require_permission, require_plan_tier
from src.api.core.dependencies import AsyncSessionDep, CurrentUserAuthDep
from src.database.models.organizations import OrganizationPermission, PlanTier
from src.api.core.messages import APIResponse, MessageCode
from src.cache.decorator import invalidate_organization_cache
from src.modules.organization.use_cases import OrganizationService
from src.modules.organization.permissions import PermissionService
from src.api.organization.schemas import (
    OrganizationCreateRequest,
    OrganizationCreateResponse,
    OrganizationUpdateRequest,
    OrganizationUpdateResponse,
    RemoveUserResponse,
    OrganizationModel,
    OrganizationUsersResponse,
    UserWithRoleData,
    OrganizationUsersData,
)

router = APIRouter(
    prefix="/organizations",
    tags=["organizations"],
)


@router.post("/", response_model=OrganizationCreateResponse)
@require_plan_tier([PlanTier.ENTERPRISE])
async def create_organization(
    request: Request,
    organization_data: OrganizationCreateRequest,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> OrganizationCreateResponse:
    """Create a new organization (enterprise users only)."""
    org_service = OrganizationService(db)

    organization = await org_service.create_organization(
        name=organization_data.name,
        user_id=current_user.user.id,
        logo_url=organization_data.logo_url,
    )

    return APIResponse.success(
        message_code=MessageCode.ORGANIZATION_CREATED,
        data=OrganizationModel.model_validate(organization),
    )


@router.patch("/", response_model=OrganizationUpdateResponse)
@require_permission(OrganizationPermission.MANAGE_ORGANIZATION)
async def update_organization(
    request: Request,
    organization_data: OrganizationUpdateRequest,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> OrganizationUpdateResponse:
    """Update organization (owner only)."""
    org_service = OrganizationService(db)
    organization = await org_service.update_organization_details(
        organization_id=current_user.organization.id,
        requesting_user_id=current_user.user.id,
        new_name=organization_data.name,
        new_logo_url=(
            str(organization_data.logo_url) if organization_data.logo_url else None
        ),
    )
    await invalidate_organization_cache(current_user.organization.id)
    return APIResponse.success(
        message_code=MessageCode.ORGANIZATION_UPDATED,
        data=OrganizationModel.model_validate(organization),
    )


@router.delete(
    "/users/{user_id}",
    response_model=RemoveUserResponse,
)
@require_permission(OrganizationPermission.MANAGE_MEMBERS)
async def remove_user_from_organization(
    user_id: UUID,
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> RemoveUserResponse:
    """Remove a user from an organization (manage members permission required)."""
    permission_service = PermissionService(db)
    organization_id = current_user.organization.id

    await permission_service.remove_user_from_organization(
        user_id=user_id,
        organization_id=organization_id,
        requesting_user_id=current_user.user.id,
    )

    await invalidate_organization_cache(organization_id)
    return APIResponse.success(
        message_code=MessageCode.USER_REMOVED_FROM_ORGANIZATION,
        data=True,
    )


@router.get(
    "/users",
    response_model=OrganizationUsersResponse,
)
@require_permission(OrganizationPermission.VIEW_MEMBERS)
async def list_organization_users_with_roles(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> OrganizationUsersResponse:
    """List all users and their roles in an organization."""
    org_service = OrganizationService(db)

    users_data = await org_service.get_organization_users_with_roles(
        current_user.organization.id
    )

    users_with_roles = [UserWithRoleData(**user_data) for user_data in users_data]

    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data=OrganizationUsersData(
            organization_id=str(current_user.organization.id),
            users=users_with_roles,
            user_count=len(users_with_roles),
        ),
    )
