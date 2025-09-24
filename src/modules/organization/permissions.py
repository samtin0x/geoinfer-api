"""Permission and role management service with dependency injection."""

from uuid import UUID

from fastapi import status
from sqlalchemy import delete, select

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.database.models import (
    OrganizationPermission,
    OrganizationRole,
    UserOrganizationRole,
)
from src.database.models.roles import has_permission, get_permissions_for_role
from src.core.base import BaseService


class PermissionService(BaseService):
    async def grant_user_role(
        self,
        user_id: UUID,
        organization_id: UUID,
        role: OrganizationRole,
        granted_by_id: UUID,
    ) -> bool:
        existing = await self.db.execute(
            select(UserOrganizationRole).where(
                UserOrganizationRole.user_id == user_id,
                UserOrganizationRole.organization_id == organization_id,
            )
        )
        existing_role = existing.scalar_one_or_none()
        if existing_role:
            if existing_role.role == role:
                return True
            existing_role.role = role
            existing_role.granted_by_id = granted_by_id
        else:
            user_role = UserOrganizationRole(
                user_id=user_id,
                organization_id=organization_id,
                role=role,
                granted_by_id=granted_by_id,
            )
            self.db.add(user_role)
        await self.db.commit()
        return True

    async def revoke_user_role(
        self,
        user_id: UUID,
        organization_id: UUID,
        role: OrganizationRole,
    ) -> bool:
        stmt = delete(UserOrganizationRole).where(
            UserOrganizationRole.user_id == user_id,
            UserOrganizationRole.organization_id == organization_id,
            UserOrganizationRole.role == role,
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount > 0

    async def revoke_user_organization_roles(
        self,
        user_id: UUID,
        organization_id: UUID,
    ) -> bool:
        stmt = delete(UserOrganizationRole).where(
            UserOrganizationRole.user_id == user_id,
            UserOrganizationRole.organization_id == organization_id,
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount > 0

    async def check_user_permission(
        self,
        user_id: UUID,
        organization_id: UUID,
        permission: OrganizationPermission,
    ) -> bool:
        stmt = select(UserOrganizationRole.role).where(
            UserOrganizationRole.user_id == user_id,
            UserOrganizationRole.organization_id == organization_id,
        )
        result = await self.db.execute(stmt)
        user_roles = result.scalars().all()
        for role in user_roles:
            if has_permission(role, permission):
                return True
        return False

    async def get_user_roles(
        self,
        user_id: UUID,
        organization_id: UUID,
    ) -> list[OrganizationRole]:
        stmt = select(UserOrganizationRole.role).where(
            UserOrganizationRole.user_id == user_id,
            UserOrganizationRole.organization_id == organization_id,
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_user_permissions(
        self,
        user_id: UUID,
        organization_id: UUID,
    ) -> set[OrganizationPermission]:
        user_roles = await self.get_user_roles(user_id, organization_id)
        all_permissions = set()
        for role in user_roles:
            role_permissions = get_permissions_for_role(role)
            all_permissions.update(role_permissions)
        return all_permissions

    @staticmethod
    def get_available_roles() -> list[OrganizationRole]:
        return list(OrganizationRole)

    @staticmethod
    def get_available_permissions() -> list[OrganizationPermission]:
        return list(OrganizationPermission)

    @staticmethod
    def get_role_permissions(role: OrganizationRole) -> set[OrganizationPermission]:
        return get_permissions_for_role(role)

    async def get_all_user_roles(self, user_id: UUID) -> list[UserOrganizationRole]:
        """Get all roles for a user across all organizations."""
        stmt = (
            select(UserOrganizationRole)
            .where(UserOrganizationRole.user_id == user_id)
            .order_by(UserOrganizationRole.granted_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def remove_user_from_organization(
        self,
        user_id: UUID,
        organization_id: UUID,
        requesting_user_id: UUID,
    ) -> None:
        has_permission = await self.check_user_permission(
            user_id=requesting_user_id,
            organization_id=organization_id,
            permission=OrganizationPermission.MANAGE_MEMBERS,
        )
        if not has_permission:
            raise GeoInferException(
                MessageCode.INSUFFICIENT_PERMISSIONS,
                status.HTTP_403_FORBIDDEN,
                {"description": "Insufficient permissions to manage members"},
            )

        if user_id == requesting_user_id:
            raise GeoInferException(
                MessageCode.CANNOT_REMOVE_YOURSELF,
                status.HTTP_400_BAD_REQUEST,
                {"description": "Cannot remove yourself from organization"},
            )

        user_roles = await self.get_user_roles(user_id, organization_id)
        if not user_roles:
            raise GeoInferException(
                MessageCode.USER_NOT_MEMBER_OF_ORGANIZATION,
                status.HTTP_400_BAD_REQUEST,
                {"description": "User is not a member of this organization"},
            )

        for role in user_roles:
            await self.revoke_user_role(
                user_id=user_id, organization_id=organization_id, role=role
            )

        from src.modules.user.management import UserManagementService

        user_management_service = UserManagementService(self.db)
        success = await user_management_service.remove_user_from_organization(user_id)
        if not success:
            raise GeoInferException(
                MessageCode.INTERNAL_SERVER_ERROR,
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                {"description": "Failed to remove user from organization"},
            )
