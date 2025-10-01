from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from fastapi import status

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.cache.decorator import invalidate_user_auth_cache
from src.database.models import (
    Organization,
    OrganizationRole,
    User,
    UserOrganizationRole,
    OrganizationPermission,
)
from src.core.base import BaseService
from src.modules.organization.permissions import PermissionService
from src.database.models.organizations import PlanTier


class OrganizationService(BaseService):
    async def get_organization_by_id(
        self, organization_id: UUID
    ) -> Organization | None:
        stmt = (
            select(Organization)
            .where(Organization.id == organization_id)
            .options(selectinload(Organization.members))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_organization(
        self,
        name: str,
        user_id: UUID,
        logo_url: str | None = None,
        organization_id: UUID | None = None,
    ) -> Organization:
        user = await self.db.get(User, user_id)
        if not user:
            raise GeoInferException(MessageCode.USER_NOT_FOUND, 404)

        user_org = await self.db.get(Organization, user.organization_id)
        if not user_org:
            raise GeoInferException(MessageCode.RESOURCE_NOT_FOUND, 404)

        from src.database.models.roles import UserOrganizationRole
        from src.database.models.organizations import OrganizationRole as OrgRole

        stmt = (
            select(UserOrganizationRole, Organization)
            .join(Organization, UserOrganizationRole.organization_id == Organization.id)
            .where(UserOrganizationRole.user_id == user_id)
            .where(UserOrganizationRole.role == OrgRole.ADMIN)
            .where(Organization.plan_tier == PlanTier.ENTERPRISE)
            .where(Organization.id != user.organization_id)
        )
        result = await self.db.execute(stmt)
        admin_enterprise_orgs = result.fetchall()
        if len(admin_enterprise_orgs) >= 1:
            raise GeoInferException(MessageCode.ORGANIZATION_LIMIT_EXCEEDED, 400)

        organization = Organization(
            id=organization_id,
            name=name,
            logo_url=logo_url,
            plan_tier=PlanTier.ENTERPRISE,
        )
        self.db.add(organization)
        await self.db.commit()
        await self.db.refresh(organization)

        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(organization_id=organization.id)
        )
        await self.db.commit()

        permission_service = PermissionService(self.db)
        await permission_service.grant_user_role(
            user_id=user_id,
            organization_id=organization.id,
            role=OrganizationRole.ADMIN,
            granted_by_id=user_id,
        )
        await invalidate_user_auth_cache(user_id)
        return organization

    async def update_organization_details(
        self,
        organization_id: UUID,
        requesting_user_id: UUID,
        new_name: str | None = None,
        new_logo_url: str | None = None,
    ) -> Organization:
        organization = await self.get_organization_by_id(organization_id)
        if not organization:
            raise GeoInferException(
                MessageCode.ORGANIZATION_NOT_FOUND,
                status.HTTP_404_NOT_FOUND,
                {"description": "Organization not found"},
            )

        permission_service = PermissionService(self.db)
        has_permission = await permission_service.check_user_permission(
            user_id=requesting_user_id,
            organization_id=organization_id,
            permission=OrganizationPermission.MANAGE_ORGANIZATION,
        )
        if not has_permission:
            raise GeoInferException(
                MessageCode.INSUFFICIENT_PERMISSIONS,
                status.HTTP_403_FORBIDDEN,
                {"description": "Insufficient permissions to update organization"},
            )
        if new_name is not None:
            organization.name = new_name
        if new_logo_url is not None:
            organization.logo_url = new_logo_url
        await self.db.commit()
        await self.db.refresh(organization)
        return organization

    async def add_user_to_organization(
        self,
        organization_id: UUID,
        user_id: UUID,
        requesting_user_id: UUID,
        role: OrganizationRole = OrganizationRole.MEMBER,
    ) -> bool:
        permission_service = PermissionService(self.db)
        has_permission = await permission_service.check_user_permission(
            user_id=requesting_user_id,
            organization_id=organization_id,
            permission=OrganizationPermission.MANAGE_MEMBERS,
        )
        if not has_permission:
            raise GeoInferException(
                MessageCode.INSUFFICIENT_PERMISSIONS,
                status.HTTP_403_FORBIDDEN,
                {"description": "Insufficient permissions to add members"},
            )
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(organization_id=organization_id)
        )
        await permission_service.grant_user_role(
            user_id=user_id,
            organization_id=organization_id,
            role=role,
            granted_by_id=requesting_user_id,
        )
        await self.db.commit()
        await invalidate_user_auth_cache(user_id)
        return True

    async def set_active_organization(
        self, user_id: UUID, organization_id: UUID
    ) -> bool:
        """Set active organization for user after checking permissions."""
        permission_service = PermissionService(self.db)
        user_roles = await permission_service.get_user_roles(user_id, organization_id)

        if not user_roles:
            raise GeoInferException(
                MessageCode.INSUFFICIENT_PERMISSIONS,
                status.HTTP_403_FORBIDDEN,
                {
                    "description": f"User does not have access to organization {organization_id}"
                },
            )

        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(organization_id=organization_id)
        )
        await self.db.commit()
        await invalidate_user_auth_cache(user_id)
        return True

    async def get_organization_users_with_roles(
        self, organization_id: UUID
    ) -> list[dict]:
        """Get all users and their roles in an organization using relationship loading."""
        stmt = (
            select(Organization)
            .where(Organization.id == organization_id)
            .options(
                selectinload(Organization.user_roles).selectinload(
                    UserOrganizationRole.user
                )
            )
        )
        result = await self.db.execute(stmt)
        organization = result.scalar_one_or_none()

        if not organization:
            raise GeoInferException(
                MessageCode.ORGANIZATION_NOT_FOUND,
                status.HTTP_404_NOT_FOUND,
                {"description": "Organization not found"},
            )

        users_with_roles = []
        for user_role in organization.user_roles:
            role_value = (
                user_role.role
                if isinstance(user_role.role, str)
                else user_role.role.value
            )
            users_with_roles.append(
                {
                    "user_id": str(user_role.user.id),
                    "name": user_role.user.name,
                    "email": user_role.user.email,
                    "role": role_value,
                    "joined_at": user_role.granted_at.isoformat(),
                }
            )

        return users_with_roles

    async def list_organizations(self, limit: int = 100) -> list[Organization]:
        stmt = select(Organization).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
