import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from sqlalchemy import select

from src.modules.billing.credits.service import CreditConsumptionService
from src.modules.billing.stripe.service import StripePaymentService
from src.database.models import (
    Subscription,
    SubscriptionStatus,
    CreditGrant,
    GrantType,
    UsagePeriod,
    Organization,
    PlanTier,
)


@pytest.mark.asyncio
class TestPauseAccessBehavior:
    """Test that pause_access properly blocks both consumption and grant creation."""

    async def test_pause_access_blocks_credit_consumption(self, db_session):
        """Test that pause_access=True blocks credit consumption."""
        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            plan_tier=PlanTier.SUBSCRIBED,
        )
        db_session.add(org)

        # Create subscription with pause_access=True
        subscription = Subscription(
            id=uuid4(),
            organization_id=org.id,
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            pause_access=True,  # ✅ Access is paused
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(subscription)

        # Create usage period
        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        db_session.add(usage_period)

        # Create credit grant (existing credits)
        credit_grant = CreditGrant(
            id=uuid4(),
            organization_id=org.id,
            subscription_id=subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Test Credits",
            amount=1000,
            remaining_amount=1000,
            expires_at=subscription.current_period_end,
        )
        db_session.add(credit_grant)
        await db_session.commit()

        # Test credit consumption service
        consumption_service = CreditConsumptionService(db_session)

        # Attempt to consume credits - should be blocked
        success, reason = await consumption_service.consume_credits(
            organization_id=org.id,
            credits_needed=100,
        )

        # Verify consumption is blocked
        assert success is False
        assert reason == "Account access paused due to payment issues"

        # Verify credits were not consumed
        await db_session.refresh(credit_grant)
        assert credit_grant.remaining_amount == 1000  # Unchanged

    async def test_pause_access_blocks_credit_grant_creation(self, db_session):
        """Test that pause_access=True prevents new credit grant creation."""
        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            plan_tier=PlanTier.SUBSCRIBED,
        )
        db_session.add(org)

        # Create subscription with pause_access=True
        subscription = Subscription(
            id=uuid4(),
            organization_id=org.id,
            stripe_subscription_id="sub_test_paused",
            stripe_customer_id="cus_test_paused",
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            pause_access=True,  # ✅ Access is paused
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(subscription)
        await db_session.commit()

        # Test Stripe service credit grant creation
        stripe_service = StripePaymentService(db_session)

        # Call _create_usage_period (simulates subscription setup)
        await stripe_service._create_usage_period(subscription)

        # Verify usage period was created
        from sqlalchemy import select

        usage_periods = await db_session.execute(
            select(UsagePeriod).where(UsagePeriod.subscription_id == subscription.id)
        )
        usage_period = usage_periods.scalar_one_or_none()
        assert usage_period is not None

        # Verify NO credit grant was created due to pause_access=True
        credit_grants = await db_session.execute(
            select(CreditGrant).where(
                CreditGrant.subscription_id == subscription.id,
                CreditGrant.grant_type == GrantType.SUBSCRIPTION,
            )
        )
        grants = credit_grants.scalars().all()
        assert len(grants) == 0  # ✅ No grants created when paused

    async def test_pause_access_false_allows_credit_grant_creation(self, db_session):
        """Test that pause_access=False allows normal credit grant creation."""
        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            plan_tier=PlanTier.SUBSCRIBED,
        )
        db_session.add(org)

        # Create subscription with pause_access=False
        subscription = Subscription(
            id=uuid4(),
            organization_id=org.id,
            stripe_subscription_id="sub_test_active",
            stripe_customer_id="cus_test_active",
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            pause_access=False,  # ✅ Access is NOT paused
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(subscription)
        await db_session.commit()

        # Test Stripe service credit grant creation
        stripe_service = StripePaymentService(db_session)

        # Call _create_usage_period (simulates subscription setup)
        await stripe_service._create_usage_period(subscription)

        # Verify credit grant WAS created
        credit_grants = await db_session.execute(
            select(CreditGrant).where(
                CreditGrant.subscription_id == subscription.id,
                CreditGrant.grant_type == GrantType.SUBSCRIPTION,
            )
        )
        grants = credit_grants.scalars().all()
        assert len(grants) == 1  # ✅ Grant created when not paused

        grant = grants[0]
        assert grant.amount == 1000
        assert grant.remaining_amount == 1000
        assert grant.description.startswith("Monthly Subscription Credits")

    async def test_payment_restoration_creates_missed_credits(self, db_session):
        """Test that payment restoration creates missed credit grants."""
        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            plan_tier=PlanTier.SUBSCRIBED,
        )
        db_session.add(org)

        # Create subscription that WAS paused
        subscription = Subscription(
            id=uuid4(),
            organization_id=org.id,
            stripe_subscription_id="sub_test_restore",
            stripe_customer_id="cus_test_restore",
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.PAST_DUE,
            pause_access=True,  # ✅ Currently paused
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(subscription)

        # Create usage period (but no credit grants due to pause)
        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        db_session.add(usage_period)
        await db_session.commit()

        # Verify no credit grants exist initially
        initial_grants = await db_session.execute(
            select(CreditGrant).where(
                CreditGrant.subscription_id == subscription.id,
                CreditGrant.grant_type == GrantType.SUBSCRIPTION,
            )
        )
        assert len(initial_grants.scalars().all()) == 0

        # Simulate payment restoration
        stripe_service = StripePaymentService(db_session)

        # Mock invoice paid data
        invoice_data = {
            "subscription": subscription.stripe_subscription_id,
            "period_start": int(subscription.current_period_start.timestamp()),
            "period_end": int(subscription.current_period_end.timestamp()),
        }

        # Call payment restoration handler
        await stripe_service._handle_invoice_paid(invoice_data)

        # Verify subscription is no longer paused
        await db_session.refresh(subscription)
        assert subscription.pause_access is False
        assert subscription.status == SubscriptionStatus.ACTIVE

        # Verify missed credit grant was created
        restored_grants = await db_session.execute(
            select(CreditGrant).where(
                CreditGrant.subscription_id == subscription.id,
                CreditGrant.grant_type == GrantType.SUBSCRIPTION,
            )
        )
        grants = restored_grants.scalars().all()
        assert len(grants) == 1  # ✅ Missed grant was created

        grant = grants[0]
        assert grant.amount == 1000
        assert grant.remaining_amount == 1000
        assert "Restored Monthly Credits" in grant.description

    async def test_pause_access_false_allows_credit_consumption(self, db_session):
        """Test that pause_access=False allows normal credit consumption."""
        # Create organization
        org = Organization(
            id=uuid4(),
            name="Test Org",
            plan_tier=PlanTier.SUBSCRIBED,
        )
        db_session.add(org)

        # Create subscription with pause_access=False
        subscription = Subscription(
            id=uuid4(),
            organization_id=org.id,
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            pause_access=False,  # ✅ Access is NOT paused
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(subscription)

        # Create usage period
        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        db_session.add(usage_period)

        # Create credit grant
        credit_grant = CreditGrant(
            id=uuid4(),
            organization_id=org.id,
            subscription_id=subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Test Credits",
            amount=1000,
            remaining_amount=1000,
            expires_at=subscription.current_period_end,
        )
        db_session.add(credit_grant)
        await db_session.commit()

        # Test credit consumption service
        consumption_service = CreditConsumptionService(db_session)

        # Attempt to consume credits - should succeed
        success, reason = await consumption_service.consume_credits(
            organization_id=org.id,
            credits_needed=100,
        )

        # Verify consumption succeeded
        assert success is True
        assert reason == "Credits consumed successfully"

        # Verify credits were consumed
        await db_session.refresh(credit_grant)
        assert credit_grant.remaining_amount == 900  # 1000 - 100
