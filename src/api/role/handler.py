"""Role domain handlers."""

from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import status

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import APIResponse, MessageCode
from src.database.models import OrganizationPermission, User, UserOrganizationRole
from src.services.organization.permissions import PermissionService
from .models import (
    UserOrganizationRoleModel,
    UserWithRoleData,
    OrganizationUsersRoleData,
    RoleDefinitionData,
    RoleDefinitionsData,
    RoleManagementData,
)
from .requests import (
    GrantRoleRequest,
    RevokeRoleRequest,
    ChangeRoleRequest,
    UserRoleResponse,
    RoleManagementResponse,
    CurrentUserRolesResponse,
)


async def grant_role_handler(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    role_data: GrantRoleRequest,
    requesting_user_id: UUID,
) -> UserRoleResponse:
    """Grant a role to a user in an organization."""
    permission_service = PermissionService(db)

    # Check if requesting user has permission to manage roles
    has_permission = await permission_service.check_user_permission(
        user_id=requesting_user_id,
        organization_id=organization_id,
        permission=OrganizationPermission.MANAGE_ROLES,
    )

    if not has_permission:
        raise GeoInferException(
            MessageCode.INSUFFICIENT_PERMISSIONS,
            status.HTTP_403_FORBIDDEN,
            {"description": "Insufficient permissions to manage roles"},
        )

    success = await permission_service.grant_user_role(
        user_id=user_id,
        organization_id=organization_id,
        role=role_data.role,
        granted_by_id=requesting_user_id,
    )

    if not success:
        raise GeoInferException(
            MessageCode.BAD_REQUEST,
            status.HTTP_400_BAD_REQUEST,
            {
                "description": "Failed to grant role - user may not exist or role already assigned"
            },
        )

    # Get the created role record for response
    stmt = select(UserOrganizationRole).where(
        UserOrganizationRole.user_id == str(user_id),
        UserOrganizationRole.organization_id == organization_id,
        UserOrganizationRole.role == role_data.role,
    )
    result = await db.execute(stmt)
    role_record = result.scalar_one_or_none()

    if not role_record:
        raise GeoInferException(
            MessageCode.RESOURCE_NOT_FOUND,
            status.HTTP_404_NOT_FOUND,
            {"description": "Role record not found after creation"},
        )

    return APIResponse.success(
        message_code=MessageCode.ROLE_GRANTED,
        message=f"Role {role_data.role.value} granted to user {user_id}",
        data=UserOrganizationRoleModel.model_validate(role_record),
    )


async def revoke_role_handler(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    role_data: RevokeRoleRequest,
    requesting_user_id: UUID,
) -> RoleManagementResponse:
    """Revoke a role from a user in an organization."""
    permission_service = PermissionService(db)

    # Check if requesting user has permission to manage roles
    has_permission = await permission_service.check_user_permission(
        user_id=requesting_user_id,
        organization_id=organization_id,
        permission=OrganizationPermission.MANAGE_ROLES,
    )

    if not has_permission:
        raise GeoInferException(
            MessageCode.INSUFFICIENT_PERMISSIONS,
            status.HTTP_403_FORBIDDEN,
            {"description": "Insufficient permissions to manage roles"},
        )

    success = await permission_service.revoke_user_role(
        user_id=user_id,
        organization_id=organization_id,
        role=role_data.role,
    )

    if not success:
        raise GeoInferException(
            MessageCode.BAD_REQUEST,
            status.HTTP_400_BAD_REQUEST,
            {
                "description": "Failed to revoke role - user may not have this role assigned"
            },
        )

    return APIResponse.success(
        message_code=MessageCode.ROLE_REVOKED,
        message=f"Role {role_data.role.value} revoked from user {user_id}",
        data=RoleManagementData(message="Role revoked successfully"),
    )


async def change_role_handler(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    role_data: ChangeRoleRequest,
    requesting_user_id: UUID,
) -> UserRoleResponse:
    """Change a user's role in an organization."""
    permission_service = PermissionService(db)

    # Check if requesting user has permission to manage roles
    has_permission = await permission_service.check_user_permission(
        user_id=requesting_user_id,
        organization_id=organization_id,
        permission=OrganizationPermission.MANAGE_ROLES,
    )

    if not has_permission:
        raise GeoInferException(
            MessageCode.INSUFFICIENT_PERMISSIONS,
            status.HTTP_403_FORBIDDEN,
            {"description": "Insufficient permissions to manage roles"},
        )

    # Prevent users from changing their own role
    if user_id == requesting_user_id:
        raise GeoInferException(
            MessageCode.CANNOT_CHANGE_OWN_ROLE,
            status.HTTP_400_BAD_REQUEST,
            {"description": "Cannot change your own role"},
        )

    # Check if user already has the role they're being assigned
    current_roles = await permission_service.get_user_roles(user_id, organization_id)
    if role_data.role in current_roles:
        raise GeoInferException(
            MessageCode.BAD_REQUEST,
            status.HTTP_400_BAD_REQUEST,
            {"description": "User already has this role assigned"},
        )

    success = await permission_service.grant_user_role(
        user_id=user_id,
        organization_id=organization_id,
        role=role_data.role,
        granted_by_id=requesting_user_id,
    )

    if not success:
        raise GeoInferException(
            MessageCode.BAD_REQUEST,
            status.HTTP_400_BAD_REQUEST,
            {
                "description": "Failed to change role - user may not exist in organization"
            },
        )

    # Get the updated role record for response
    stmt = select(UserOrganizationRole).where(
        UserOrganizationRole.user_id == str(user_id),
        UserOrganizationRole.organization_id == organization_id,
        UserOrganizationRole.role == role_data.role,
    )
    result = await db.execute(stmt)
    role_record = result.scalar_one_or_none()

    if not role_record:
        raise GeoInferException(
            MessageCode.RESOURCE_NOT_FOUND,
            status.HTTP_404_NOT_FOUND,
            {"description": "Role record not found after update"},
        )

    return APIResponse.success(
        message_code=MessageCode.ROLE_CHANGED,
        message=f"Role changed to {role_data.role.value} for user {user_id}",
        data=UserOrganizationRoleModel.model_validate(role_record),
    )


async def list_role_definitions_handler() -> APIResponse:
    """List all available roles and their permissions (static definitions)."""
    # Get all roles and their permissions using static methods
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


async def list_organization_users_with_roles_handler(
    db: AsyncSession,
    organization_id: UUID,
    requesting_user_id: UUID,
) -> APIResponse:
    """List all users and their roles in an organization."""
    permission_service = PermissionService(db)

    # Check if requesting user has permission to view members
    has_permission = await permission_service.check_user_permission(
        user_id=requesting_user_id,
        organization_id=organization_id,
        permission=OrganizationPermission.VIEW_MEMBERS,
    )

    if not has_permission:
        raise GeoInferException(
            MessageCode.INSUFFICIENT_PERMISSIONS,
            status.HTTP_403_FORBIDDEN,
            {"description": "Insufficient permissions to view organization members"},
        )

    # Get all users with roles in this organization
    stmt = (
        select(
            UserOrganizationRole.user_id,
            UserOrganizationRole.role,
            User.name,
            User.email,
        )
        .join(User, UserOrganizationRole.user_id == User.id)
        .where(UserOrganizationRole.organization_id == organization_id)
    )

    result = await db.execute(stmt)
    user_roles = result.all()

    users_with_roles = []
    for user_id, role, name, email in user_roles:
        role_value = role if isinstance(role, str) else role.value
        users_with_roles.append(
            UserWithRoleData(
                user_id=str(user_id),
                name=name,
                email=email,
                role=role_value,
            )
        )

    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data=OrganizationUsersRoleData(
            organization_id=str(organization_id),
            users=users_with_roles,
            user_count=len(users_with_roles),
        ),
    )


async def get_current_user_roles_handler(
    db: AsyncSession,
    user_id: UUID,
) -> CurrentUserRolesResponse:
    """Get all roles for the current user across all organizations."""
    stmt = (
        select(UserOrganizationRole)
        .where(UserOrganizationRole.user_id == user_id)
        .order_by(UserOrganizationRole.granted_at.desc())
    )

    result = await db.execute(stmt)
    user_roles = result.scalars().all()

    roles_data = [UserOrganizationRoleModel.model_validate(role) for role in user_roles]

    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data=roles_data,
    )
