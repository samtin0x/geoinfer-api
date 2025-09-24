"""Stripe payment management service."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import stripe  # type: ignore
from stripe import StripeError  # type: ignore
from sqlalchemy import select, func

from src.api.core.constants import FREE_TRIAL_SIGNUP_CREDIT_AMOUNT
from src.database.models import (
    PlanTier,
    Subscription,
    SubscriptionStatus,
    TopUp,
)
from src.core.base import BaseService
from src.utils.settings.stripe import StripeSettings
from src.modules.billing.constants import (
    STRIPE_PRICE_MAP,
    CREDIT_PACKAGES,
    StripeProductType,
)


class StripePaymentService(BaseService):
    def __init__(self, db):
        super().__init__(db)
        stripe.api_key = StripeSettings().STRIPE_SECRET_KEY.get_secret_value()

    def get_plan_pricing(self, plan_tier: PlanTier) -> dict:
        if plan_tier == PlanTier.FREE:
            return {
                "monthly": None,
                "yearly": None,
                "credits": FREE_TRIAL_SIGNUP_CREDIT_AMOUNT,
                "price_monthly": Decimal("0.00"),
                "price_yearly": Decimal("0.00"),
            }
        return STRIPE_PRICE_MAP.get(plan_tier, {})

    def get_credit_package_pricing(self, package_size: str) -> dict:
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
        try:
            checkout_session = stripe.checkout.Session.create(
                customer_email=customer_email,
                payment_method_types=["card"],
                line_items=[{"price": price_id, "quantity": 1}],
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
            return checkout_session
        except StripeError as e:
            raise ValueError(f"Failed to create checkout session: {e}")

    async def create_customer_portal_session(
        self, customer_id: str, return_url: str
    ) -> stripe.billing_portal.Session:
        try:
            portal_session = stripe.billing_portal.Session.create(
                customer=customer_id, return_url=return_url
            )
            return portal_session
        except StripeError as e:
            raise ValueError(f"Failed to create portal session: {e}")

    def validate_webhook_signature(self, payload: bytes, signature: str) -> dict:
        try:
            event = stripe.Webhook.construct_event(
                payload,
                signature,
                StripeSettings().STRIPE_WEBHOOK_SECRET,
            )
            return event
        except Exception as e:
            raise ValueError(str(e))

    async def handle_subscription_webhook(self, event: dict) -> bool:
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
                return False
            return True
        except Exception:
            return False

    async def _handle_subscription_created(self, subscription_data: dict) -> None:
        stripe_subscription_id = subscription_data["id"]
        customer_id = subscription_data["customer"]
        status_val = subscription_data["status"]
        organization = await self._get_organization_by_stripe_customer(customer_id)
        if not organization:
            return
        price_id = subscription_data["items"]["data"][0]["price"]["id"]
        plan_tier = self._get_plan_tier_from_price_id(price_id)
        if not plan_tier:
            return
        plan_info = self.get_plan_pricing(plan_tier)
        monthly_credits = plan_info.get("monthly_credits", 1000)
        import json

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
                if status_val == "active"
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

    async def _handle_subscription_updated(self, subscription_data: dict) -> None:
        return None

    async def _handle_subscription_deleted(self, subscription_data: dict) -> None:
        return None

    async def _handle_payment_succeeded(self, invoice_data: dict) -> None:
        subscription_id = invoice_data.get("subscription")
        if not subscription_id:
            return
        stmt = select(Subscription).where(
            Subscription.stripe_subscription_id == subscription_id
        )
        result = await self.db.execute(stmt)
        subscription = result.scalar_one_or_none()
        if not subscription:
            return
        billing_reason = invoice_data.get("billing_reason")
        if billing_reason == "subscription_cycle":
            await self._create_monthly_credit_package(subscription, invoice_data)
        elif billing_reason == "subscription_create":
            subscription.current_period_start = datetime.fromtimestamp(
                invoice_data["period_start"], timezone.utc
            )
            subscription.current_period_end = datetime.fromtimestamp(
                invoice_data["period_end"], timezone.utc
            )
            subscription.status = SubscriptionStatus.ACTIVE
            await self.db.commit()

    async def _create_monthly_credit_package(
        self, subscription: Subscription, invoice_data: dict
    ) -> None:
        monthly_credits = subscription.monthly_allowance
        now = datetime.fromtimestamp(invoice_data["period_start"], timezone.utc)
        month_end = now.replace(day=1, month=now.month + 1) - timedelta(days=1)
        month_end = month_end.replace(hour=23, minute=59, second=59)
        from src.database.models import GrantType, CreditGrant

        topup = TopUp(
            id=uuid4(),
            organization_id=subscription.organization_id,
            credits_purchased=monthly_credits,
            price_paid=0,
            description="Monthly Credits",
            stripe_payment_intent_id=invoice_data.get("payment_intent"),
            package_type=GrantType.TOPUP,
            expires_at=month_end,
        )
        self.db.add(topup)
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

    async def _handle_payment_failed(self, invoice_data: dict) -> None:
        return None

    async def _get_organization_by_stripe_customer(self, customer_id: str):
        return None

    def _get_plan_tier_from_price_id(self, price_id: str) -> PlanTier | None:
        price_to_plan: dict[str, PlanTier | None] = {}
        return price_to_plan.get(price_id)


class BillingQueryService(BaseService):
    """Read service for billing products (subscriptions and credit packages)."""

    async def fetch_subscriptions(
        self, organization_id, limit: int, offset: int
    ) -> tuple[list[Subscription], int]:
        stmt = (
            select(Subscription)
            .where(Subscription.organization_id == organization_id)
            .order_by(Subscription.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        subscriptions = result.scalars().all()

        total_stmt = select(func.count(Subscription.id)).where(
            Subscription.organization_id == organization_id
        )
        total_result = await self.db.execute(total_stmt)
        total = total_result.scalar() or 0
        return list(subscriptions), total

    async def fetch_topups(
        self, organization_id, limit: int, offset: int
    ) -> tuple[list[TopUp], int]:
        stmt = (
            select(TopUp)
            .where(TopUp.organization_id == organization_id)
            .order_by(TopUp.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        topups = result.scalars().all()

        total_stmt = select(func.count(TopUp.id)).where(
            TopUp.organization_id == organization_id
        )
        total_result = await self.db.execute(total_stmt)
        total = total_result.scalar() or 0
        return list(topups), total
