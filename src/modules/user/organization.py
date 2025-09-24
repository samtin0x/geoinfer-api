"""User organization service with caching."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.database.models.users import User
from src.database.models.organizations import Organization
from src.core.base import BaseService
from src.cache import (
    cached,
    invalidate_user_organization_cache,
    invalidate_user_roles_cache,
    invalidate_user_permissions_cache,
)


class UserOrganizationService(BaseService):
    """Service for managing user organization relationships with caching."""

    @cached(ttl=1800)
    async def get_user_organization_id(self, user_id: UUID) -> UUID | None:
        stmt = select(User.organization_id).where(User.id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    @cached(ttl=1800)
    async def get_user_organization(self, user_id: UUID) -> Organization | None:
        stmt = (
            select(User)
            .options(selectinload(User.organization))
            .where(User.id == user_id)
        )
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            return None
        return user.organization

    async def invalidate_user_organization_cache(self, user_id: UUID) -> None:
        await invalidate_user_organization_cache(user_id)

    async def invalidate_organization_cache_for_all_members(
        self, organization_id: UUID
    ) -> int:
        stmt = select(User.id).where(User.organization_id == organization_id)
        result = await self.db.execute(stmt)
        user_ids = result.scalars().all()
        for user_id in user_ids:
            await self.invalidate_user_organization_cache(user_id)
        return 0

    async def update_user_organization(
        self, user_id: UUID, organization_id: UUID | None
    ) -> None:
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
            await self.invalidate_user_organization_cache(user_id)
            if old_org_id:
                await invalidate_user_roles_cache(user_id, old_org_id)
                await invalidate_user_permissions_cache(user_id, old_org_id)
            if organization_id:
                await invalidate_user_roles_cache(user_id, organization_id)
                await invalidate_user_permissions_cache(user_id, organization_id)
