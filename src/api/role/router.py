"""Role domain router."""

from uuid import UUID
from fastapi import APIRouter, Request, status

from src.api.core.decorators.auth import require_permission
from src.api.core.dependencies import AsyncSessionDep, CurrentUserAuthDep
from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import APIResponse, MessageCode
from src.database.models.organizations import OrganizationPermission
from src.modules.organization.permissions import PermissionService
from src.api.role.schemas import (
    ChangeRoleRequest,
    RoleChangeResponse,
    OrganizationRoleListResponse,
    CurrentUserRolesResponse,
    UserOrganizationRoleModel,
    RoleDefinitionData,
    RoleDefinitionsData,
)

router = APIRouter(
    prefix="/roles",
    tags=["roles"],
)


@router.patch(
    "/organizations/{organization_id}/users/{user_id}",
    response_model=RoleChangeResponse,
)
@require_permission(OrganizationPermission.MANAGE_ROLES)
async def change_role(
    organization_id: UUID,
    user_id: UUID,
    request: Request,
    role_data: ChangeRoleRequest,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> RoleChangeResponse:
    """Change a user's role in an organization."""
    if user_id == current_user.user.id:
        raise GeoInferException(
            MessageCode.CANNOT_CHANGE_OWN_ROLE,
            status.HTTP_400_BAD_REQUEST,
            {"description": "Cannot change your own role"},
        )

    permission_service = PermissionService(db)

    success = await permission_service.grant_user_role(
        user_id=user_id,
        organization_id=organization_id,
        role=role_data.role,
        granted_by_id=current_user.user.id,
    )

    if not success:
        raise GeoInferException(
            MessageCode.BAD_REQUEST,
            status.HTTP_400_BAD_REQUEST,
            {
                "description": "Failed to change role - user may not exist in organization"
            },
        )

    return APIResponse.success(
        message_code=MessageCode.ROLE_CHANGED,
        message=f"Role changed to {role_data.role.value} for user {user_id}",
        data=True,
    )


@router.get("/definitions", response_model=OrganizationRoleListResponse)
async def list_role_definitions(
    request: Request,
    current_user: CurrentUserAuthDep,
) -> OrganizationRoleListResponse:
    """List all available roles and their permissions (static definitions)."""
    available_roles = PermissionService.get_available_roles()
    available_permissions = PermissionService.get_available_permissions()

    roles_with_permissions = []
    for role in available_roles:
        permissions = PermissionService.get_role_permissions(role)
        roles_with_permissions.append(
            RoleDefinitionData(
                role=role.value, permissions=[perm.value for perm in permissions]
            )
        )

    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data=RoleDefinitionsData(
            roles=roles_with_permissions,
            all_permissions=[perm.value for perm in available_permissions],
        ),
    )


@router.get("/", response_model=CurrentUserRolesResponse)
async def get_current_user_roles(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> CurrentUserRolesResponse:
    """Get all roles for the current user across all organizations."""
    permission_service = PermissionService(db)
    user_roles = await permission_service.get_all_user_roles(current_user.user.id)

    roles_data = [UserOrganizationRoleModel.model_validate(role) for role in user_roles]

    return APIResponse.success(message_code=MessageCode.SUCCESS, data=roles_data)
