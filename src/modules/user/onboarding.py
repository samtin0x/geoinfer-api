from typing import cast
from uuid import UUID

import resend
from sqlalchemy import select

from src.api.core.constants import SHOULD_SEND_WELCOME_EMAIL
from src.core.base import BaseService
from src.database.models import Organization, PlanTier, User
from src.database.models.organizations import OrganizationRole
from src.emails.render import SUPPORTED_LOCALES, LocaleType, render_email
from src.modules.billing.credits import CreditConsumptionService
from src.modules.organization.permissions import PermissionService
from src.utils.settings.email import EmailSettings


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

        await self._create_stripe_customer_for_organization(organization, user)

        await self._send_welcome_email(user.email, user.locale)

        return user, organization

    async def _create_stripe_customer_for_organization(
        self,
        organization: Organization,
        user: User,
    ) -> None:
        """Create a Stripe customer for the organization during onboarding.

        Args:
            organization: The organization to create the customer for
            user: The user being onboarded (provides email, name, and locale)
        """
        try:
            import stripe
            from src.utils.settings.stripe import StripeSettings

            # Set Stripe API key
            stripe.api_key = StripeSettings().STRIPE_SECRET_KEY.get_secret_value()

            # Build customer creation params
            customer_params: dict = {
                "email": user.email,
                "name": user.name or organization.name,
                "metadata": {
                    "organization_id": str(organization.id),
                    "organization_name": organization.name,
                },
            }

            # Add user name to metadata if provided
            if user.name:
                customer_params["metadata"]["user_name"] = user.name

            # Set preferred locale for Stripe communications (invoices, receipts, etc.)
            # Locale comes from JWT claims (user_metadata.locale or payload.locale)
            if user.locale:
                customer_params["preferred_locales"] = [user.locale]

            # Create Stripe customer
            customer = stripe.Customer.create(**customer_params)

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

    async def _send_welcome_email(self, email: str, locale: str | None = None) -> None:
        """Send welcome email to new user based on their locale."""
        if not SHOULD_SEND_WELCOME_EMAIL:
            self.logger.debug(
                f"Welcome email disabled by SHOULD_SEND_WELCOME_EMAIL flag for {email}"
            )
            return

        try:
            email_settings = EmailSettings()

            if not email_settings.RESEND_API_KEY:
                self.logger.warning(
                    f"RESEND_API_KEY not configured, skipping welcome email for {email}"
                )
                return

            resend.api_key = email_settings.RESEND_API_KEY

            valid_locale: LocaleType = "en"
            if locale and locale in SUPPORTED_LOCALES:
                valid_locale = cast(LocaleType, locale)

            email_data = render_email(template_name="invite", locale=valid_locale)

            from_address = f"{email_settings.EMAIL_FROM_NAME} <{email_settings.EMAIL_FROM_ADDRESS}@{email_settings.EMAIL_FROM_DOMAIN}>"

            response = resend.Emails.send(
                {
                    "from": from_address,
                    "to": email,
                    "subject": email_data["subject"],
                    "html": email_data["html"],
                    "reply_to": email_data["reply_to"],
                    "tags": [{"name": "category", "value": "onboarding"}],
                }
            )

            self.logger.info(
                f"Welcome email sent successfully to {email}",
                email_id=response["id"],
                locale=valid_locale,
            )

        except Exception as e:
            self.logger.warning(
                f"Failed to send welcome email to {email}: {e}",
                error=str(e),
            )

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
