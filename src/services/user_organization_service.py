"""User organization service with caching."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.database.models.users import User
from src.database.models.organizations import Organization
from src.services.base import BaseService
from src.cache import (
    cached,
    invalidate_user_organization_cache,
    invalidate_user_roles_cache,
    invalidate_user_permissions_cache,
)


class UserOrganizationService(BaseService):
    """Service for managing user organization relationships with caching."""

    @cached(ttl=1800)  # 30 minutes
    async def get_user_organization_id(self, user_id: UUID) -> UUID | None:
        """
        Get user's organization ID with automatic caching.

        Args:
            user_id: User ID to get organization for

        Returns:
            Organization ID if user belongs to one, None otherwise
        """
        # Query database
        stmt = select(User.organization_id).where(User.id == user_id)
        result = await self.db.execute(stmt)
        organization_id = result.scalar_one_or_none()

        self.logger.debug(f"Queried user organization for {user_id}: {organization_id}")
        return organization_id

    @cached(ttl=1800)  # 30 minutes
    async def get_user_organization(self, user_id: UUID) -> Organization | None:
        """
        Get user's full organization data with automatic caching.

        Args:
            user_id: User ID to get organization for

        Returns:
            Organization object if user belongs to one, None otherwise
        """
        # Query database with full organization data
        stmt = (
            select(User)
            .options(selectinload(User.organization))
            .where(User.id == user_id)
        )
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            return None

        organization = user.organization
        self.logger.debug(
            f"Queried user organization data for {user_id}: {organization}"
        )
        return organization

    async def invalidate_user_organization_cache(self, user_id: UUID) -> None:
        """
        Invalidate cached organization data for a user.

        This should be called when:
        - User joins an organization
        - User leaves an organization
        - Organization data changes

        Args:
            user_id: User ID to invalidate cache for
        """
        await invalidate_user_organization_cache(user_id)
        self.logger.info(f"Invalidated organization cache for user {user_id}")

    async def invalidate_organization_cache_for_all_members(
        self, organization_id: UUID
    ) -> int:
        """
        Invalidate organization cache for all members of an organization.

        This should be called when organization data changes.

        Args:
            organization_id: Organization ID

        Returns:
            Number of cache keys deleted
        """
        # Get all user IDs in the organization
        stmt = select(User.id).where(User.organization_id == organization_id)
        result = await self.db.execute(stmt)
        user_ids = result.scalars().all()

        total_deleted = 0
        for user_id in user_ids:
            await self.invalidate_user_organization_cache(user_id)
            # Note: cache invalidation doesn't return a count currently

        self.logger.info(
            f"Invalidated organization cache for all members of org {organization_id}: {total_deleted} keys deleted"
        )
        return total_deleted

    async def update_user_organization(
        self, user_id: UUID, organization_id: UUID | None
    ) -> None:
        """
        Update user's organization and invalidate cache.

        Args:
            user_id: User ID to update
            organization_id: New organization ID (None to remove from organization)
        """
        # Update database
        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            old_org_id = user.organization_id
            if organization_id is not None:
                user.organization_id = organization_id
            else:
                user.organization_id = None  # type: ignore
            await self.db.commit()

            # Invalidate cache for the user
            await self.invalidate_user_organization_cache(user_id)

            # Also invalidate role and permission caches
            if old_org_id:
                await invalidate_user_roles_cache(user_id, old_org_id)
                await invalidate_user_permissions_cache(user_id, old_org_id)
            if organization_id:
                await invalidate_user_roles_cache(user_id, organization_id)
                await invalidate_user_permissions_cache(user_id, organization_id)

            self.logger.info(
                f"Updated user {user_id} organization: {old_org_id} -> {organization_id}"
            )
