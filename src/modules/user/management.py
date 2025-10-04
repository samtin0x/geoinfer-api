"""Unified user management service with authentication, onboarding, and user operations."""

from cachetools import TTLCache
from uuid import UUID
from sqlalchemy import select

from src.cache.decorator import (
    cached,
    invalidate_plan_tier_cache,
)
from src.database.models import User, Organization, PlanTier
from src.modules.user.jwt_claims import extract_user_data_from_jwt
from src.core.base import BaseService
from src.modules.user.onboarding import UserOnboardingService
from src.utils.logger import get_logger

logger = get_logger(__name__)

# In-memory cache for user onboarding status (5 minutes TTL)
ONBOARDING_CACHE: TTLCache[str, bool] = TTLCache(maxsize=1000, ttl=300)


class UserManagementService(BaseService):
    """
    Unified service for user management, authentication, and onboarding operations.

    Combines functionality from UserAuthService and UserManagementService.
    """

    # User Management Operations
    async def get_user_by_id(self, user_id: UUID) -> User | None:
        """Get user by ID."""
        return await self.db.get(User, user_id)

    async def get_user_by_email(self, email: str) -> User | None:
        """Get user by email."""
        stmt = select(User).where(User.email == email)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_user(
        self,
        user_id: UUID,
        email: str,
        name: str | None = None,
        plan_tier: PlanTier = PlanTier.FREE,
    ) -> User:
        """Create a new user."""
        user = User(
            id=user_id,
            email=email,
            name=name or "",
        )

        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        self.logger.info(f"Created user {user_id} with email {email}")
        return user

    async def update_user_plan_tier(
        self, user_id: UUID, plan_tier: PlanTier
    ) -> User | None:
        """Update user's organization plan tier and invalidate relevant caches."""
        user = await self.get_user_by_id(user_id)
        if not user:
            return None

        # Update plan tier on user's organization
        organization = await self.db.get(Organization, user.organization_id)
        if not organization:
            self.logger.error(
                f"Organization {user.organization_id} not found for user {user_id}"
            )
            return None

        organization.plan_tier = plan_tier

        await self.db.commit()
        await self.db.refresh(user)
        await self.db.refresh(organization)

        # Use comprehensive cache invalidation for plan tier changes
        await invalidate_plan_tier_cache(user_id, organization.id)

        self.logger.info(
            f"Updated user {user_id} organization plan to {plan_tier} and invalidated all relevant caches"
        )
        return user

    async def get_organization_members(self, organization_id: UUID) -> list[User]:
        """Get all members of an organization."""
        stmt = select(User).where(User.organization_id == organization_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_user_organization(self, user_id: UUID) -> Organization | None:
        """Get user's organization (organization ID = user ID)."""
        # User organization ID is the same as user ID
        return await self.db.get(Organization, user_id)

    async def remove_user_from_organization(self, user_id: UUID) -> bool:
        """Remove user from their current organization and set to user org."""
        user = await self.get_user_by_id(user_id)
        if not user:
            return False

        old_org_id = user.organization_id

        # Ensure the user organization exists, create if needed
        user_org = await self.get_user_organization(user_id)
        if not user_org:
            onboarding_service = UserOnboardingService(self.db)
            _, user_org = await onboarding_service.ensure_user_onboarded(
                user_id=user_id,
                email=user.email,
                name=user.name,
                plan_tier=PlanTier.FREE,
                locale=user.locale,
            )

        # Set user's organization to their user organization (user ID)
        user.organization_id = user_id
        await self.db.commit()

        # Invalidate user auth cache (includes onboarding cache)
        from src.cache.decorator import (
            invalidate_user_auth_cache,
            invalidate_onboarding_cache,
        )

        await invalidate_user_auth_cache(user_id)
        await invalidate_onboarding_cache(user_id)

        self.logger.info(
            f"Removed user {user_id} from organization {old_org_id}, set to user org {user_id}, and invalidated caches"
        )
        return True

    @cached(10800)
    async def ensure_user_onboarded_cached(
        self,
        user_id: UUID,
        email: str,
        name: str | None = None,
        plan_tier: PlanTier = PlanTier.FREE,
        avatar_url: str | None = None,
        locale: str | None = None,
    ) -> tuple[User, Organization]:
        """
        Ensure user is onboarded with user organization (cached).
        """
        onboarding_service = UserOnboardingService(self.db)
        user, user_org = await onboarding_service.ensure_user_onboarded(
            user_id=user_id,
            email=email,
            name=name,
            plan_tier=plan_tier,
            avatar_url=avatar_url,
            locale=locale,
        )
        logger.debug(f"User {user_id} onboarded")
        return user, user_org

    async def validate_organization_access(
        self,
        user_id: UUID,
        organization_id: UUID,
        is_api_key_auth: bool = False,
    ) -> Organization:
        """Validate that user has access to the specified organization."""
        from src.database.models import UserOrganizationRole
        from src.api.core.exceptions.base import GeoInferException
        from src.api.core.messages import MessageCode
        from fastapi import status

        stmt = select(Organization).where(
            Organization.id == organization_id,
            (Organization.user_id == user_id)
            | (
                Organization.id.in_(
                    select(UserOrganizationRole.organization_id).where(
                        UserOrganizationRole.user_id == user_id
                    )
                )
            ),
        )
        result = await self.db.execute(stmt)
        valid_org = result.scalar_one_or_none()
        if not valid_org:
            auth_type = "API key owner" if is_api_key_auth else "User"
            raise GeoInferException(
                MessageCode.FORBIDDEN,
                status.HTTP_403_FORBIDDEN,
                {
                    "description": f"{auth_type} does not have access to organization {organization_id}"
                },
            )
        return valid_org

    async def handle_jwt_authentication(
        self,
        payload: dict,
    ) -> tuple[User, Organization]:
        """Handle JWT authentication with onboarding and org validation."""
        user_data = extract_user_data_from_jwt(payload)
        user_id = user_data["user_id"]
        email = user_data["email"]
        name = user_data["name"]
        avatar_url = user_data["avatar_url"]
        locale = user_data["locale"]

        if not user_id or not email:
            from src.api.core.exceptions.base import GeoInferException
            from src.api.core.messages import MessageCode
            from fastapi import status

            raise GeoInferException(
                MessageCode.INVALID_TOKEN,
                status.HTTP_401_UNAUTHORIZED,
                {"description": "JWT token missing required user_id or email"},
            )

        user, user_org = await self.ensure_user_onboarded_cached(
            user_id=user_id,
            email=email,
            name=name,
            plan_tier=PlanTier.FREE,
            avatar_url=avatar_url,
            locale=locale,
        )
        return user, user_org
