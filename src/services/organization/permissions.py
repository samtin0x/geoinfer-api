"""Permission and role management service with dependency injection."""

from uuid import UUID

from sqlalchemy import delete, select
from src.database.models import (
    OrganizationPermission,
    OrganizationRole,
    UserOrganizationRole,
)
from src.database.models.roles import has_permission, get_permissions_for_role
from src.services.base import BaseService


class PermissionService(BaseService):
    """Service for permission and role management using pure Python logic."""

    async def grant_user_role(
        self,
        user_id: UUID,
        organization_id: UUID,
        role: OrganizationRole,
        granted_by_id: UUID,
    ) -> bool:
        """Grant a role to a user in an organization (replaces any existing role)."""

        # Check if user already has any role in this organization
        existing = await self.db.execute(
            select(UserOrganizationRole).where(
                UserOrganizationRole.user_id == user_id,
                UserOrganizationRole.organization_id == organization_id,
            )
        )
        existing_role = existing.scalar_one_or_none()

        if existing_role:
            if existing_role.role == role:
                self.logger.info(f"User {user_id} already has role {role.value}")
                return True
            else:
                # Update existing role instead of creating new one
                existing_role.role = role
                existing_role.granted_by_id = granted_by_id
                self.logger.info(
                    "Updated user %s role to %s",
                    user_id,
                    role.value,
                )
        else:
            # Create new role assignment
            user_role = UserOrganizationRole(
                user_id=user_id,
                organization_id=organization_id,
                role=role,
                granted_by_id=granted_by_id,
            )
            self.db.add(user_role)
            self.logger.info("Granted role %s to user %s", role.value, user_id)

        await self.db.commit()
        return True

    async def revoke_user_role(
        self,
        user_id: UUID,
        organization_id: UUID,
        role: OrganizationRole,
    ) -> bool:
        """Revoke a role from a user in an organization."""
        stmt = delete(UserOrganizationRole).where(
            UserOrganizationRole.user_id == user_id,
            UserOrganizationRole.organization_id == organization_id,
            UserOrganizationRole.role == role,
        )

        result = await self.db.execute(stmt)
        await self.db.commit()

        if result.rowcount > 0:
            self.logger.info(f"Revoked role {role.value} from user {user_id}")
            return True
        return False

    async def revoke_user_organization_roles(
        self,
        user_id: UUID,
        organization_id: UUID,
    ) -> bool:
        """Revoke all roles from a user in an organization."""
        stmt = delete(UserOrganizationRole).where(
            UserOrganizationRole.user_id == user_id,
            UserOrganizationRole.organization_id == organization_id,
        )

        result = await self.db.execute(stmt)
        await self.db.commit()

        if result.rowcount > 0:
            self.logger.info(
                f"Revoked all roles from user {user_id} in org {organization_id}"
            )
            return True
        return False

    async def check_user_permission(
        self,
        user_id: UUID,
        organization_id: UUID,
        permission: OrganizationPermission,
    ) -> bool:
        """Check if user has specific permission in organization."""
        # Get user's roles in organization
        stmt = select(UserOrganizationRole.role).where(
            UserOrganizationRole.user_id == user_id,
            UserOrganizationRole.organization_id == organization_id,
        )

        result = await self.db.execute(stmt)
        user_roles = result.scalars().all()

        # Check if any role has the required permission using pure Python logic
        for role in user_roles:
            if has_permission(role, permission):
                return True

        return False

    async def get_user_roles(
        self,
        user_id: UUID,
        organization_id: UUID,
    ) -> list[OrganizationRole]:
        """Get all roles for a user in an organization."""
        stmt = select(UserOrganizationRole.role).where(
            UserOrganizationRole.user_id == user_id,
            UserOrganizationRole.organization_id == organization_id,
        )

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_user_organization_roles(
        self,
        user_id: UUID,
        organization_id: UUID,
    ) -> list[OrganizationRole]:
        """Get all roles for a user in an organization."""
        return await self.get_user_roles(user_id, organization_id)

    async def get_user_permissions(
        self,
        user_id: UUID,
        organization_id: UUID,
    ) -> set[OrganizationPermission]:
        """Get all permissions for a user in an organization."""
        user_roles = await self.get_user_roles(user_id, organization_id)

        # Collect all permissions from all user roles
        all_permissions = set()
        for role in user_roles:
            role_permissions = get_permissions_for_role(role)
            all_permissions.update(role_permissions)

        return all_permissions

    @staticmethod
    def get_available_roles() -> list[OrganizationRole]:
        """Get all available organization roles."""
        return list(OrganizationRole)

    @staticmethod
    def get_available_permissions() -> list[OrganizationPermission]:
        """Get all available organization permissions."""
        return list(OrganizationPermission)

    @staticmethod
    def get_role_permissions(role: OrganizationRole) -> set[OrganizationPermission]:
        """Get permissions for a specific role (pure Python logic)."""
        return get_permissions_for_role(role)

    async def remove_user_from_organization(
        self,
        user_id: UUID,
        organization_id: UUID,
        requesting_user_id: UUID,
    ) -> bool:
        """Remove a user from an organization and assign them to their personal organization."""

        # Check if requesting user has permission to manage members
        has_permission = await self.check_user_permission(
            user_id=requesting_user_id,
            organization_id=organization_id,
            permission=OrganizationPermission.MANAGE_MEMBERS,
        )

        if not has_permission:
            return False

        # Prevent users from removing themselves
        if user_id == requesting_user_id:
            return False

        # Get user's current roles in the organization
        user_roles = await self.get_user_roles(user_id, organization_id)

        if not user_roles:
            # User is not a member of this organization
            return False

        # Revoke all roles for the user in this organization
        for role in user_roles:
            await self.revoke_user_role(
                user_id=user_id,
                organization_id=organization_id,
                role=role,
            )

        # Move user to their personal organization
        from src.services.user.user_management import UserManagementService

        user_management_service = UserManagementService(self.db)
        success = await user_management_service.remove_user_from_organization(user_id)

        if success:
            self.logger.info(
                f"Removed user {user_id} from organization {organization_id}"
            )
            return True
        return False
