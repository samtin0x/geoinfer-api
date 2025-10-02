from uuid import UUID
from sqlalchemy import select

from src.database.models import User, Organization, PlanTier
from src.core.base import BaseService
from src.modules.organization.permissions import PermissionService
from src.database.models.organizations import OrganizationRole
from src.modules.billing.credits import CreditConsumptionService


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
        user = await self.db.get(User, user_id)
        if not user:
            return await self._create_user_with_organization(
                user_id=user_id,
                email=email,
                name=name,
                plan_tier=plan_tier,
                avatar_url=avatar_url,
                locale=locale,
            )
        await self._update_user_info(user, name, avatar_url, locale)
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
        organization = Organization(
            id=user_id,
            name=email,
            logo_url=None,
            plan_tier=plan_tier,
        )
        self.db.add(organization)
        await self.db.flush()

        user = User(
            id=user_id,
            email=email,
            name=name or "",
            avatar_url=avatar_url,
            locale=locale,
            organization_id=user_id,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        await self.db.refresh(organization)

        permission_service = PermissionService(self.db)
        await permission_service.grant_user_role(
            user_id=user_id,
            organization_id=organization.id,
            role=OrganizationRole.ADMIN,
            granted_by_id=user_id,
        )

        credit_service = CreditConsumptionService(self.db)
        await credit_service.grant_trial_credits_to_user(
            organization_id=organization.id,
            user_id=user_id,
        )

        await self._create_stripe_customer_for_organization(organization, email)

        return user, organization

    async def _create_stripe_customer_for_organization(
        self, organization: Organization, email: str
    ) -> None:
        """Create a Stripe customer for the organization during onboarding."""
        try:
            import stripe
            from src.utils.settings.stripe import StripeSettings

            # Set Stripe API key
            stripe.api_key = StripeSettings().STRIPE_SECRET_KEY.get_secret_value()

            # Create Stripe customer
            customer = stripe.Customer.create(
                email=email,
                name=organization.name,
                metadata={
                    "organization_id": str(organization.id),
                    "organization_name": organization.name,
                },
            )

            # Store customer ID in organization
            organization.stripe_customer_id = customer.id
            await self.db.commit()

            self.logger.info(
                f"Created Stripe customer {customer.id} for organization {organization.id} during onboarding"
            )

        except Exception as e:
            # Log error but don't fail onboarding - customer can be created later during checkout
            self.logger.warning(
                f"Failed to create Stripe customer for organization {organization.id} during onboarding: {e}"
            )

    async def _update_user_info(
        self,
        user: User,
        name: str | None = None,
        avatar_url: str | None = None,
        locale: str | None = None,
    ) -> None:
        updated = False
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

    async def get_user_organizations(self, user_id: UUID) -> list[Organization]:
        from src.database.models.roles import UserOrganizationRole
        from sqlalchemy import case

        user = await self.db.get(User, user_id)
        if not user:
            return []

        stmt = (
            select(Organization)
            .join(
                UserOrganizationRole,
                Organization.id == UserOrganizationRole.organization_id,
            )
            .where(UserOrganizationRole.user_id == user_id)
            .order_by(
                case(
                    (Organization.id == user.organization_id, 0),
                    else_=1,
                ),
                Organization.created_at.desc(),
            )
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
