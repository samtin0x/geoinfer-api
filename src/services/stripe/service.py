"""Stripe payment management service."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import stripe  # type: ignore
from stripe import StripeError, SignatureVerificationError  # type: ignore
from sqlalchemy import select

from src.api.core.constants import FREE_TRIAL_SIGNUP_CREDIT_AMOUNT
from src.cache.decorator import invalidate_user_auth_cache
from src.database.models import (
    PlanTier,
    User,
    Subscription,
    SubscriptionStatus,
    TopUp,
)
from src.services.base import BaseService
from src.utils.settings.stripe import StripeSettings
from .constants import STRIPE_PRICE_MAP, CREDIT_PACKAGES, StripeProductType


class StripePaymentService(BaseService):
    """Service for Stripe operations."""

    def __init__(self, db):
        super().__init__(db)
        stripe.api_key = StripeSettings().STRIPE_SECRET_KEY

    def get_plan_pricing(self, plan_tier: PlanTier) -> dict:
        """Get pricing information for a plan tier."""
        if plan_tier == PlanTier.FREE:
            return {
                "monthly": None,
                "yearly": None,
                "credits": FREE_TRIAL_SIGNUP_CREDIT_AMOUNT,  # Trial credits granted during onboarding
                "price_monthly": Decimal("0.00"),
                "price_yearly": Decimal("0.00"),
            }

        return STRIPE_PRICE_MAP.get(plan_tier, {})

    def get_credit_package_pricing(self, package_size: str) -> dict:
        """Get pricing for credit packages."""
        return CREDIT_PACKAGES.get(package_size, {})

    async def create_checkout_session(
        self,
        customer_email: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        organization_id: UUID,
        product_type: StripeProductType = StripeProductType.SUBSCRIPTION,
    ) -> stripe.checkout.Session:
        """Create a Stripe checkout session."""
        try:
            checkout_session = stripe.checkout.Session.create(
                customer_email=customer_email,
                payment_method_types=["card"],
                line_items=[
                    {
                        "price": price_id,
                        "quantity": 1,
                    }
                ],
                mode=(
                    "subscription"
                    if product_type == StripeProductType.SUBSCRIPTION
                    else "payment"
                ),
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "organization_id": organization_id,
                    "product_type": product_type.value,
                },
                allow_promotion_codes=True,
            )

            self.logger.info(
                f"Created checkout session {checkout_session.id} for org {organization_id}"
            )
            return checkout_session

        except StripeError as e:
            self.logger.error(f"Stripe error creating checkout session: {e}")
            raise ValueError(f"Failed to create checkout session: {e}")

    async def create_customer_portal_session(
        self,
        customer_id: str,
        return_url: str,
    ) -> stripe.billing_portal.Session:
        """Create a customer portal session for managing subscriptions."""
        try:
            portal_session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )

            self.logger.info(
                f"Created customer portal session for customer {customer_id}"
            )
            return portal_session

        except StripeError as e:
            self.logger.error(f"Stripe error creating portal session: {e}")
            raise ValueError(f"Failed to create portal session: {e}")

    async def handle_subscription_webhook(self, event: dict) -> bool:
        """Handle Stripe subscription webhook events."""
        event_type = event["type"]
        data = event["data"]["object"]

        try:
            if event_type == "customer.subscription.created":
                await self._handle_subscription_created(data)
            elif event_type == "customer.subscription.updated":
                await self._handle_subscription_updated(data)
            elif event_type == "customer.subscription.deleted":
                await self._handle_subscription_deleted(data)
            elif event_type == "invoice.payment_succeeded":
                await self._handle_payment_succeeded(data)
            elif event_type == "invoice.payment_failed":
                await self._handle_payment_failed(data)
            else:
                self.logger.info(f"Unhandled webhook event type: {event_type}")
                return False

            return True

        except Exception as e:
            self.logger.error(f"Error handling webhook {event_type}: {e}")
            return False

    async def _handle_subscription_created(self, subscription_data: dict) -> None:
        """Handle subscription created webhook."""
        from datetime import datetime, timezone

        stripe_subscription_id = subscription_data["id"]
        customer_id = subscription_data["customer"]
        status = subscription_data["status"]

        # Find organization by Stripe customer ID
        # This assumes you have a way to map Stripe customer ID to organization
        # You might need to add a stripe_customer_id field to your Organization model
        organization = await self._get_organization_by_stripe_customer(customer_id)

        if not organization:
            self.logger.warning(
                f"No organization found for Stripe customer {customer_id}"
            )
            return

        # Get plan details
        price_id = subscription_data["items"]["data"][0]["price"]["id"]
        plan_tier = self._get_plan_tier_from_price_id(price_id)

        if not plan_tier:
            self.logger.warning(f"Unknown price ID {price_id}")
            return

        # Calculate credits based on plan
        plan_info = self.get_plan_pricing(plan_tier)
        monthly_credits = plan_info.get("monthly_credits", 1000)

        # Create subscription record
        import json

        # Create metadata with subscription start date and other info
        metadata = {
            "original_subscription_start": datetime.fromtimestamp(
                subscription_data["current_period_start"], timezone.utc
            ).isoformat(),
            "plan_type": plan_tier.value if plan_tier else "unknown",
            "stripe_price_id": price_id,
        }

        subscription = Subscription(
            id=uuid4(),
            organization_id=organization.id,
            stripe_subscription_id=stripe_subscription_id,
            description=f"Monthly {plan_tier.value if plan_tier else 'Unknown'} Plan",
            metadata_json=json.dumps(metadata),
            status=(
                SubscriptionStatus.ACTIVE
                if status == "active"
                else SubscriptionStatus.INACTIVE
            ),
            monthly_allowance=monthly_credits,
            price_paid=subscription_data.get("amount_paid", 0.0),
            current_period_start=datetime.fromtimestamp(
                subscription_data["current_period_start"], timezone.utc
            ),
            current_period_end=datetime.fromtimestamp(
                subscription_data["current_period_end"], timezone.utc
            ),
        )

        self.db.add(subscription)
        await self.db.commit()

        # Create initial credit grant for subscription
        from src.database.models import CreditGrant, GrantType

        credit_grant = CreditGrant(
            id=uuid4(),
            organization_id=organization.id,
            subscription_id=subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description=f"Monthly {plan_tier.value if plan_tier else 'Unknown'} Plan Credits",
            amount=monthly_credits,
            remaining_amount=monthly_credits,
            expires_at=datetime.fromtimestamp(
                subscription_data["current_period_end"], timezone.utc
            ),
        )
        self.db.add(credit_grant)
        await self.db.commit()

        self.logger.info(
            f"Created subscription record for {stripe_subscription_id} with {monthly_credits} monthly credits"
        )

        # Invalidate cache for affected users
        await self._invalidate_cache_for_subscription(stripe_subscription_id)

    async def _handle_subscription_updated(self, subscription_data: dict) -> None:
        """Handle subscription updated webhook."""
        stripe_subscription_id = subscription_data["id"]
        self.logger.info(f"Subscription updated: {stripe_subscription_id}")

        # Invalidate cache for affected users
        await self._invalidate_cache_for_subscription(stripe_subscription_id)

    async def _handle_subscription_deleted(self, subscription_data: dict) -> None:
        """Handle subscription deleted webhook."""
        stripe_subscription_id = subscription_data["id"]
        self.logger.info(f"Subscription deleted: {stripe_subscription_id}")

        # Invalidate cache for affected users
        await self._invalidate_cache_for_subscription(stripe_subscription_id)

    async def _handle_payment_succeeded(self, invoice_data: dict) -> None:
        """Handle successful payment webhook."""
        subscription_id = invoice_data.get("subscription")
        self.logger.info(f"Payment succeeded for invoice: {invoice_data['id']}")

        if subscription_id:
            # Get subscription details
            stmt = select(Subscription).where(
                Subscription.stripe_subscription_id == subscription_id
            )
            result = await self.db.execute(stmt)
            subscription = result.scalar_one_or_none()

            if not subscription:
                self.logger.warning(f"No subscription found for {subscription_id}")
                return

            billing_reason = invoice_data.get("billing_reason")

            if billing_reason == "subscription_cycle":
                # Handle monthly billing cycle for annual plans
                await self._handle_monthly_credit_allocation(subscription, invoice_data)
            elif billing_reason == "subscription_create":
                # Handle initial subscription creation
                await self._handle_initial_subscription_payment(
                    subscription, invoice_data
                )

            await self._invalidate_cache_for_subscription(subscription_id)

    async def _handle_initial_subscription_payment(
        self, subscription: Subscription, invoice_data: dict
    ) -> None:
        """Handle initial subscription payment (first payment)."""

        # Update subscription with current period
        subscription.current_period_start = datetime.fromtimestamp(
            invoice_data["period_start"], timezone.utc
        )
        subscription.current_period_end = datetime.fromtimestamp(
            invoice_data["period_end"], timezone.utc
        )
        subscription.status = SubscriptionStatus.ACTIVE

        # For annual plans, create first month's credit package
        # Check if this is an annual plan by looking at the period duration
        period_duration = invoice_data["period_end"] - invoice_data["period_start"]
        is_annual_plan = period_duration > 30 * 24 * 3600  # More than 30 days

        if is_annual_plan:
            await self._create_monthly_credit_package(subscription, invoice_data)

        await self.db.commit()
        self.logger.info(
            f"Initialized subscription {subscription.stripe_subscription_id}"
        )

    async def _handle_monthly_credit_allocation(
        self, subscription: Subscription, invoice_data: dict
    ) -> None:
        """Handle monthly credit allocation for annual plans."""

        # For annual plans, we create monthly credit packages
        # Check if this is an annual plan by looking at the period duration
        period_duration = invoice_data["period_end"] - invoice_data["period_start"]
        is_annual_plan = period_duration > 30 * 24 * 3600  # More than 30 days

        if is_annual_plan:
            # Create a new credit package for this month
            await self._create_monthly_credit_package(subscription, invoice_data)
        else:
            # For monthly plans, reset the subscription period
            subscription.current_period_start = datetime.fromtimestamp(
                invoice_data["period_start"], timezone.utc
            )
            subscription.current_period_end = datetime.fromtimestamp(
                invoice_data["period_end"], timezone.utc
            )

        await self.db.commit()
        self.logger.info(
            f"Allocated monthly credits for subscription {subscription.stripe_subscription_id}"
        )

    async def _create_monthly_credit_package(
        self, subscription: Subscription, invoice_data: dict
    ) -> None:
        """Create a monthly credit package for annual plan subscribers."""

        # Use the subscription's monthly allowance for credit package
        monthly_credits = subscription.monthly_allowance

        # Create credit package that expires at the end of this month
        now = datetime.fromtimestamp(invoice_data["period_start"], timezone.utc)
        month_end = now.replace(day=1, month=now.month + 1) - timedelta(days=1)
        month_end = month_end.replace(hour=23, minute=59, second=59)

        from src.database.models import GrantType

        topup = TopUp(
            id=uuid4(),
            organization_id=subscription.organization_id,
            credits_purchased=monthly_credits,
            price_paid=0,  # Credits are already paid for annually
            description="Monthly Credits",
            stripe_payment_intent_id=invoice_data.get("payment_intent"),
            package_type=GrantType.TOPUP,
            expires_at=month_end,
        )

        self.db.add(topup)

        # Create credit grant record
        from src.database.models import CreditGrant, GrantType

        credit_grant = CreditGrant(
            id=uuid4(),
            organization_id=subscription.organization_id,
            subscription_id=subscription.id,
            topup_id=topup.id,
            grant_type=GrantType.TOPUP,
            description=f"Monthly Credit Allocation - {now.strftime('%B %Y')}",
            amount=monthly_credits,
            remaining_amount=monthly_credits,
            expires_at=month_end,
        )
        self.db.add(credit_grant)

        await self.db.commit()
        self.logger.info(
            f"Created monthly credit package with {monthly_credits} credits for subscription {subscription.id}"
        )

    async def _handle_payment_failed(self, invoice_data: dict) -> None:
        """Handle failed payment webhook."""
        subscription_id = invoice_data.get("subscription")
        self.logger.info(f"Payment failed for invoice: {invoice_data['id']}")

        if subscription_id:
            await self._invalidate_cache_for_subscription(subscription_id)

    async def _invalidate_cache_for_subscription(
        self, stripe_subscription_id: str
    ) -> None:
        """Invalidate cache for all users in the organization affected by subscription change."""
        from src.database.models import Subscription

        # Find the subscription by Stripe ID
        stmt = select(Subscription).where(
            Subscription.stripe_subscription_id == stripe_subscription_id
        )
        result = await self.db.execute(stmt)
        subscription = result.scalar_one_or_none()

        if not subscription:
            self.logger.warning(
                f"No subscription found for Stripe ID: {stripe_subscription_id}"
            )
            return

        # Get all users in the organization
        stmt = select(User).where(User.organization_id == subscription.organization_id)
        result = await self.db.execute(stmt)
        users = result.scalars().all()

        # Invalidate cache for each user
        for user in users:
            await invalidate_user_auth_cache(user.id)

        self.logger.info(
            f"Invalidated cache for {len(users)} users in organization {subscription.organization_id}"
        )

    def validate_webhook_signature(
        self,
        payload: bytes,
        signature: str,
    ) -> dict:
        """Validate Stripe webhook signature and return event."""
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, StripeSettings().STRIPE_WEBHOOK_SECRET
            )
            return event
        except ValueError:
            raise ValueError("Invalid payload")
        except SignatureVerificationError:
            raise ValueError("Invalid signature")

    def get_all_plans(self) -> dict[str, dict]:
        """Get all available plans with pricing."""
        plans = {}
        for plan_tier in PlanTier:
            plans[plan_tier.value] = self.get_plan_pricing(plan_tier)
        return plans

    def get_all_credit_packages(self) -> dict[str, dict]:
        """Get all available credit packages."""
        return CREDIT_PACKAGES.copy()

    async def _get_organization_by_stripe_customer(self, customer_id: str):
        """Get organization by Stripe customer ID."""

        # This is a placeholder - you need to implement this based on your data model
        # Option 1: Add stripe_customer_id to Organization model
        # Option 2: Store customer_id in a mapping table
        # Option 3: Get it from the user who created the checkout session

        # For now, return None - this needs to be implemented
        return None

    def _get_plan_tier_from_price_id(self, price_id: str) -> PlanTier | None:
        """Get plan tier from Stripe price ID."""
        # This maps Stripe price IDs to your plan tiers
        # You need to define this mapping based on your Stripe setup

        price_to_plan: dict[str, PlanTier | None] = {
            # Add your Stripe price IDs here
            # "price_stripe_pro_monthly": PlanTier.PRO,
            # "price_stripe_pro_yearly": PlanTier.PRO,
        }

        return price_to_plan.get(price_id)
