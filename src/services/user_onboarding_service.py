from uuid import UUID
from sqlalchemy import select

from src.database.models import User, Organization, PlanTier
from src.services.base import BaseService
from src.services.organization.permissions import PermissionService
from src.database.models.organizations import OrganizationRole
from src.services.prediction.credits import PredictionCreditService


class UserOnboardingService(BaseService):
    """Service for handling user onboarding and user organization creation."""

    async def ensure_user_onboarded(
        self,
        user_id: UUID,
        email: str,
        name: str | None = None,
        plan_tier: PlanTier = PlanTier.FREE,
        avatar_url: str | None = None,
        locale: str | None = None,
    ) -> tuple[User, Organization]:
        """
        Ensure user is properly onboarded with user organization.

        Creates user if doesn't exist, and ensures they have a user organization.
        This should be called on first login or when user data is synced from JWT.

        Returns:
            Tuple of (User, UserOrganization)
        """
        # Check if user exists
        user = await self.db.get(User, user_id)

        if not user:
            # Create new user with organization
            return await self._create_user_with_organization(
                user_id=user_id,
                email=email,
                name=name,
                plan_tier=plan_tier,
                avatar_url=avatar_url,
                locale=locale,
            )

        # Update existing user info if needed
        await self._update_user_info(user, name, avatar_url, locale)

        # Get user's organization (guaranteed to exist for onboarded users)
        organization = await self.db.get(Organization, user.organization_id)
        if not organization:
            raise ValueError(
                f"Organization {user.organization_id} not found for user {user.id}"
            )

        return user, organization

    async def _create_user_with_organization(
        self,
        user_id: UUID,
        email: str,
        name: str | None = None,
        plan_tier: PlanTier = PlanTier.FREE,
        avatar_url: str | None = None,
        locale: str | None = None,
    ) -> tuple[User, Organization]:
        """Create a new user with their organization atomically."""

        # Step 1: Create organization first (no foreign key dependencies)
        organization = Organization(
            id=user_id,  # User org ID = user ID
            name=email,  # Use email as organization name
            logo_url=None,
            plan_tier=plan_tier,
        )
        self.db.add(organization)
        await self.db.flush()  # Create organization in database first

        # Step 2: Create user (organization now exists, so foreign key is valid)
        user = User(
            id=user_id,
            email=email,
            name=name or "",
            avatar_url=avatar_url,
            locale=locale,
            organization_id=user_id,  # References the organization we just created
        )
        self.db.add(user)

        # Step 3: Commit both changes
        await self.db.commit()
        await self.db.refresh(user)
        await self.db.refresh(organization)

        # Grant admin role to the user for their organization

        permission_service = PermissionService(self.db)
        await permission_service.grant_user_role(
            user_id=user_id,
            organization_id=organization.id,
            role=OrganizationRole.ADMIN,
            granted_by_id=user_id,
        )

        # Grant trial credits to new users

        credit_service = PredictionCreditService(self.db)
        await credit_service.grant_trial_credits_to_user(
            organization_id=organization.id,
            user_id=user_id,
        )

        self.logger.info(
            f"Created user {user_id} with organization {organization.id} and granted trial credits"
        )
        return user, organization

    async def _update_user_info(
        self,
        user: User,
        name: str | None = None,
        avatar_url: str | None = None,
        locale: str | None = None,
    ) -> None:
        """Update user info if needed (sync from JWT)."""
        updated = False

        # Only update fields if they're currently null/empty, preserve existing values once set
        if not user.name and name:
            user.name = name
            updated = True
        if not user.avatar_url and avatar_url:
            user.avatar_url = avatar_url
            updated = True
        if not user.locale and locale:
            user.locale = locale
            updated = True

        if updated:
            await self.db.commit()
            await self.db.refresh(user)
            self.logger.info(f"Updated user {user.id} info")

    async def get_user_organizations(self, user_id: UUID) -> list[Organization]:
        """Get all organizations the user is a member of via roles."""
        from src.database.models.roles import UserOrganizationRole

        stmt = (
            select(Organization)
            .join(
                UserOrganizationRole,
                Organization.id == UserOrganizationRole.organization_id,
            )
            .where(UserOrganizationRole.user_id == user_id)
        )

        result = await self.db.execute(stmt)
        return list(result.scalars().all())
