"""Organization service with dependency injection."""

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
    OrganizationPermission,
)
from src.services.base import BaseService
from src.services.organization.permissions import PermissionService
from src.database.models.organizations import PlanTier


class OrganizationService(BaseService):
    """Service for organization management operations.

    This service focuses on business logic while relying on API layer validation
    for authentication, permissions, plan tiers, and data format validation.
    """

    async def get_organization_by_id(
        self, organization_id: UUID
    ) -> Organization | None:
        """Get organization by ID with members loaded."""
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
        """Create a new organization.

        Note: API layer already validates enterprise plan tier requirements.
        Only enterprise users can reach this service method.
        """
        # Business logic: Get user's current organization
        user = await self.db.get(User, user_id)
        if not user:
            raise GeoInferException(MessageCode.USER_NOT_FOUND, 404)

        user_org = await self.db.get(Organization, user.organization_id)
        if not user_org:
            raise GeoInferException(MessageCode.RESOURCE_NOT_FOUND, 404)

        # Check organization limit: users can only create 1 extra enterprise organization
        # Count existing enterprise organizations (excluding personal org) where the user is an admin
        from src.database.models.roles import UserOrganizationRole
        from src.database.models.organizations import OrganizationRole

        # Get all organizations where the user is an admin (excluding their personal organization)
        stmt = (
            select(UserOrganizationRole, Organization)
            .join(Organization, UserOrganizationRole.organization_id == Organization.id)
            .where(UserOrganizationRole.user_id == user_id)
            .where(UserOrganizationRole.role == OrganizationRole.ADMIN)
            .where(Organization.plan_tier == PlanTier.ENTERPRISE)
            .where(
                Organization.id != user.organization_id
            )  # Exclude personal organization
        )
        result = await self.db.execute(stmt)
        admin_enterprise_orgs = result.fetchall()

        # Only allow creation if user has less than 1 extra enterprise organization
        if len(admin_enterprise_orgs) >= 1:
            raise GeoInferException(MessageCode.ORGANIZATION_LIMIT_EXCEEDED, 400)

        # Business logic: Create organization with enterprise tier (API layer validates user has enterprise plan)
        organization = Organization(
            id=organization_id,  # Use provided ID or let it auto-generate
            name=name,
            logo_url=logo_url,
            plan_tier=PlanTier.ENTERPRISE,
        )

        self.db.add(organization)
        await self.db.commit()
        await self.db.refresh(organization)

        # Update user to be part of this organization
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(organization_id=organization.id)
        )
        await self.db.commit()

        # Grant owner role

        permission_service = PermissionService(self.db)
        await permission_service.grant_user_role(
            user_id=user_id,
            organization_id=organization.id,
            role=OrganizationRole.ADMIN,
            granted_by_id=user_id,
        )

        # Invalidate user auth cache (includes onboarding cache)
        await invalidate_user_auth_cache(user_id)

        self.logger.info(
            f"Created organization {organization.id} for user {user_id} and invalidated cache"
        )
        return organization

    async def update_organization_details(
        self,
        organization_id: UUID,
        new_name: str | None = None,
        new_logo_url: str | None = None,
        requesting_user_id: UUID | None = None,
    ) -> Organization | None:
        """Update organization details.

        Note: API layer already validates user permissions and organization access.
        """
        organization = await self.get_organization_by_id(organization_id)
        if not organization:
            return None

        # Check permissions if requesting user provided
        if requesting_user_id:
            from src.services.organization.permissions import PermissionService

            permission_service = PermissionService(self.db)
            from src.database.models import OrganizationPermission

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

        # Update fields
        if new_name is not None:
            organization.name = new_name
        if new_logo_url is not None:
            organization.logo_url = new_logo_url

        await self.db.commit()
        await self.db.refresh(organization)

        self.logger.info(f"Updated organization {organization_id}")
        return organization

    async def add_user_to_organization(
        self,
        organization_id: UUID,
        user_id: UUID,
        requesting_user_id: UUID,
        role: OrganizationRole = OrganizationRole.MEMBER,
    ) -> bool:
        """Add user to organization with role.

        Note: API layer already validates user permissions and organization access.
        """
        # Check permissions

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

        # Update user's organization
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(organization_id=organization_id)
        )

        # Grant role
        await permission_service.grant_user_role(
            user_id=user_id,
            organization_id=organization_id,
            role=role,
            granted_by_id=requesting_user_id,
        )

        await self.db.commit()

        # Invalidate user auth cache (includes onboarding cache)
        await invalidate_user_auth_cache(user_id)

        self.logger.info(
            f"Added user {user_id} to organization {organization_id} and invalidated cache"
        )
        return True

    async def set_active_organization(
        self, user_id: UUID, organization_id: UUID
    ) -> Organization | None:
        """Set a specific organization as active for a user."""

        # Verify the organization exists
        organization = await self.get_organization_by_id(organization_id)
        if not organization:
            self.logger.warning(f"Organization {organization_id} not found")
            return None

        # Update user's organization_id to set active organization
        user_update_stmt = (
            update(User)
            .where(User.id == user_id)
            .values(organization_id=organization_id)
        )
        result = await self.db.execute(user_update_stmt)
        await self.db.commit()

        if result.rowcount > 0:
            # Invalidate user auth cache
            await invalidate_user_auth_cache(user_id)
            self.logger.info(
                f"Set organization {organization_id} as active for user {user_id}"
            )
            return organization
        else:
            self.logger.warning(
                f"Failed to update active organization for user {user_id}"
            )
            return None

    async def list_organizations(self, limit: int = 100) -> list[Organization]:
        """List all organizations."""
        stmt = select(Organization).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
