"""Role domain router."""

from uuid import UUID
from fastapi import APIRouter, Request

from src.api.core.decorators.auth import require_permission
from src.api.core.dependencies import AsyncSessionDep, CurrentUserAuthDep
from src.database.models.organizations import OrganizationPermission
from .handler import (
    grant_role_handler,
    change_role_handler,
    list_role_definitions_handler,
    list_organization_users_with_roles_handler,
    get_current_user_roles_handler,
)
from .requests import (
    GrantRoleRequest,
    ChangeRoleRequest,
    UserRoleResponse,
    OrganizationUsersRoleListResponse,
    OrganizationRoleListResponse,
    CurrentUserRolesResponse,
)

router = APIRouter(
    prefix="/roles",
    tags=["roles"],
)


@router.post(
    "/organizations/{organization_id}/users/{user_id}", response_model=UserRoleResponse
)
@require_permission(OrganizationPermission.MANAGE_ROLES)
async def grant_role(
    organization_id: UUID,
    user_id: UUID,
    request: Request,
    role_data: GrantRoleRequest,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> UserRoleResponse:
    """Grant a role to a user in an organization."""

    return await grant_role_handler(
        db=db,
        organization_id=organization_id,
        user_id=user_id,
        role_data=role_data,
        requesting_user_id=current_user.user.id,
    )


@router.patch(
    "/organizations/{organization_id}/users/{user_id}",
    response_model=UserRoleResponse,
)
@require_permission(OrganizationPermission.MANAGE_ROLES)
async def change_role(
    organization_id: UUID,
    user_id: UUID,
    request: Request,
    role_data: ChangeRoleRequest,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> UserRoleResponse:
    """Change a user's role in an organization."""

    return await change_role_handler(
        db=db,
        organization_id=organization_id,
        user_id=user_id,
        role_data=role_data,
        requesting_user_id=current_user.user.id,
    )


@router.get("/definitions", response_model=OrganizationRoleListResponse)
async def list_role_definitions(
    request: Request,
    current_user: CurrentUserAuthDep,
) -> OrganizationRoleListResponse:
    """List all available roles and their permissions (static definitions)."""

    return await list_role_definitions_handler()


@router.get("/", response_model=CurrentUserRolesResponse)
async def get_current_user_roles(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> CurrentUserRolesResponse:
    """Get all roles for the current user across all organizations."""

    return await get_current_user_roles_handler(
        db=db,
        user_id=current_user.user.id,
    )


@router.get(
    "/organizations/{organization_id}/users",
    response_model=OrganizationUsersRoleListResponse,
)
@require_permission(OrganizationPermission.VIEW_MEMBERS)
async def list_organization_users_with_roles(
    organization_id: UUID,
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> OrganizationUsersRoleListResponse:
    """List all users and their roles in an organization."""

    return await list_organization_users_with_roles_handler(
        db=db,
        organization_id=organization_id,
        requesting_user_id=current_user.user.id,
    )
