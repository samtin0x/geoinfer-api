"""Organization domain router."""

from uuid import UUID
from fastapi import APIRouter, Request

from src.api.core.decorators.auth import require_permission, require_plan_tier
from src.api.core.dependencies import AsyncSessionDep, CurrentUserAuthDep
from src.database.models.organizations import OrganizationPermission, PlanTier
from .handler import (
    create_organization_handler,
    update_organization_handler,
    remove_user_from_organization_handler,
)
from .requests import (
    OrganizationCreateRequest,
    OrganizationCreateResponse,
    OrganizationUpdateRequest,
    OrganizationUpdateResponse,
    RemoveUserResponse,
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
    return await create_organization_handler(
        db=db,
        organization_data=organization_data,
        user_id=current_user.user.id,
    )


@router.patch("/{organization_id}", response_model=OrganizationUpdateResponse)
@require_permission(OrganizationPermission.MANAGE_ORGANIZATION)
async def update_organization(
    organization_id: UUID,
    request: Request,
    organization_data: OrganizationUpdateRequest,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> OrganizationUpdateResponse:
    """Update organization (owner only)."""

    return await update_organization_handler(
        db=db,
        organization_id=organization_id,
        organization_data=organization_data,
        requesting_user_id=current_user.user.id,
    )


@router.delete(
    "/{organization_id}/users/{user_id}",
    response_model=RemoveUserResponse,
)
@require_permission(OrganizationPermission.MANAGE_MEMBERS)
async def remove_user_from_organization(
    organization_id: UUID,
    user_id: UUID,
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> RemoveUserResponse:
    """Remove a user from an organization (manage members permission required)."""

    return await remove_user_from_organization_handler(
        db=db,
        organization_id=organization_id,
        user_id=user_id,
        requesting_user_id=current_user.user.id,
    )
