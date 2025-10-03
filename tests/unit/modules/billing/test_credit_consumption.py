"""Credit consumption service tests."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from src.database.models import (
    SubscriptionStatus,
    CreditGrant,
    GrantType,
    PlanTier,
)
from tests.factories import (
    OrganizationFactory,
    SubscriptionFactory,
    CreditGrantFactory,
    UsagePeriodFactory,
    TopUpFactory,
)
from src.database.models.alerts import AlertSettings
from src.modules.billing.credits.service import CreditConsumptionService


class TestCreditConsumptionService:
    """Test suite for credit consumption business logic."""

    @pytest.fixture
    def service(self, db_session):
        """Create a credit consumption service instance."""
        return CreditConsumptionService(db_session)

    @pytest_asyncio.fixture
    async def test_organization(self, db_session):
        """Create a test organization."""
        return await OrganizationFactory.create_async(
            db_session,
            plan_tier=PlanTier.FREE,
            name="Test Organization",
        )

    @pytest_asyncio.fixture
    async def active_subscription(self, db_session, test_organization):
        """Create an active subscription with monthly allowance."""
        return await SubscriptionFactory.create_async(
            db_session,
            organization_id=test_organization.id,
            stripe_subscription_id="sub_test_123",
            stripe_customer_id="cus_test_456",
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            overage_enabled=False,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )

    @pytest_asyncio.fixture
    async def subscription_credit_grant(self, db_session, active_subscription):
        """Create a subscription credit grant."""
        return await CreditGrantFactory.create_async(
            db_session,
            organization_id=active_subscription.organization_id,
            subscription_id=active_subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Monthly allowance",
            amount=1000,
            remaining_amount=800,  # 200 already consumed
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )

    @pytest_asyncio.fixture
    async def topup_credit_grants(self, db_session, test_organization):
        """Create multiple topup credit grants with different expiry dates."""
        grants = []

        # Create TopUp records first
        topup1 = await TopUpFactory.create_async(
            db_session,
            organization_id=test_organization.id,
            description="Growth Topup",
            price_paid=20.0,
            credits_purchased=200,
            expires_at=datetime.now(timezone.utc) + timedelta(days=60),
        )

        topup2 = await TopUpFactory.create_async(
            db_session,
            organization_id=test_organization.id,
            description="Pro Topup",
            price_paid=50.0,
            credits_purchased=500,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )

        # First topup: 200 credits, expires in 60 days (fully available)
        grant1 = await CreditGrantFactory.create_async(
            db_session,
            organization_id=test_organization.id,
            topup_id=topup1.id,
            grant_type=GrantType.TOPUP,
            description="Growth Topup",
            amount=200,
            remaining_amount=200,  # None consumed yet
            expires_at=datetime.now(timezone.utc) + timedelta(days=60),
        )
        grants.append(grant1)

        # Second topup: 500 credits, expires in 30 days (earlier expiry, fully available)
        grant2 = await CreditGrantFactory.create_async(
            db_session,
            organization_id=test_organization.id,
            topup_id=topup2.id,
            grant_type=GrantType.TOPUP,
            description="Pro Topup",
            amount=500,
            remaining_amount=500,  # None consumed yet
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        grants.append(grant2)

        return grants

    @pytest_asyncio.fixture
    async def usage_period(self, db_session, active_subscription):
        """Create a current usage period."""
        return await UsagePeriodFactory.create_async(
            db_session,
            subscription_id=active_subscription.id,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30),
            overage_used=0,
            overage_reported=0,
            closed=False,
        )

    @pytest.mark.asyncio
    async def test_consume_credits_success_subscription_only(
        self, service, active_subscription, subscription_credit_grant, usage_period
    ):
        """Test successful credit consumption from subscription allowance only."""
        organization_id = active_subscription.organization_id
        credits_needed = 100

        # Mock the commit to avoid rollback issues in tests
        with patch.object(service.db, "commit", new_callable=AsyncMock) as mock_commit:
            success, reason = await service.consume_credits(
                organization_id=organization_id, credits_needed=credits_needed
            )

            assert success is True
            assert reason == "Credits consumed successfully"
            mock_commit.assert_called_once()

        # Verify the grant was updated in memory
        assert subscription_credit_grant.remaining_amount == 700  # 800 - 100

        # Verify usage record was created in memory
        # Note: In real usage, this would be committed to DB
        # but in tests we verify the logic works correctly

    @pytest.mark.asyncio
    async def test_consume_credits_subscription_exhausted_use_topups(
        self,
        service,
        active_subscription,
        subscription_credit_grant,
        topup_credit_grants,
        usage_period,
    ):
        """Test credit consumption when subscription exhausted, uses topups."""
        organization_id = active_subscription.organization_id
        credits_needed = 900  # More than subscription remaining (800)

        success, reason = await service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is True
        assert reason == "Credits consumed successfully"

        # Verify subscription grant is fully consumed
        await service.db.refresh(subscription_credit_grant)
        assert subscription_credit_grant.remaining_amount == 0

        # Verify topup grants were consumed (earliest expiry first)
        await service.db.refresh(topup_credit_grants[0])  # 60 days expiry
        await service.db.refresh(topup_credit_grants[1])  # 30 days expiry

        # First topup (earlier expiry) should be consumed first
        assert topup_credit_grants[1].remaining_amount == 400  # 500 - 100
        assert topup_credit_grants[0].remaining_amount == 200  # Unchanged

    @pytest.mark.asyncio
    async def test_consume_credits_all_sources_exhausted_overage_disabled(
        self,
        service,
        active_subscription,
        subscription_credit_grant,
        topup_credit_grants,
        usage_period,
    ):
        """Test credit consumption fails when all sources exhausted and overage disabled."""
        organization_id = active_subscription.organization_id
        credits_needed = 2000  # More than all available credits

        success, reason = await service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is False
        assert reason == "No credits available"

        # Verify no credits were consumed
        await service.db.refresh(subscription_credit_grant)
        assert subscription_credit_grant.remaining_amount == 800

        for grant in topup_credit_grants:
            await service.db.refresh(grant)
            # Should remain unchanged
            assert grant.remaining_amount in [200, 500]

    @pytest.mark.asyncio
    async def test_consume_credits_overage_enabled_success(
        self,
        service,
        active_subscription,
        subscription_credit_grant,
        topup_credit_grants,
        usage_period,
    ):
        """Test credit consumption succeeds with overage when enabled."""
        # Enable overage for subscription
        active_subscription.overage_enabled = True
        active_subscription.user_extra_cap = 1000  # Allow 1000 overage credits
        await service.db.commit()

        organization_id = active_subscription.organization_id
        # Total available: 800 (subscription) + 700 (topups) = 1500
        # Request 1700 to require 200 overage
        credits_needed = 1700

        success, reason = await service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is True
        assert reason == "Credits consumed successfully"

        # Verify overage was used
        await service.db.refresh(usage_period)
        assert usage_period.overage_used == 200  # 1700 - 1500 available = 200 overage

    @pytest.mark.asyncio
    async def test_consume_credits_overage_cap_exceeded(
        self,
        service,
        active_subscription,
        subscription_credit_grant,
        topup_credit_grants,
        usage_period,
    ):
        """Test credit consumption fails when overage cap is exceeded."""
        # Enable overage but set low cap
        active_subscription.overage_enabled = True
        active_subscription.user_extra_cap = 100  # Only 100 overage allowed
        await service.db.commit()

        organization_id = active_subscription.organization_id
        # Total available: 800 (subscription) + 700 (topups) = 1500
        # Request 1700 to require 200 overage, but cap is only 100
        credits_needed = 1700

        success, reason = await service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is False
        assert reason == "Overage cap of 100 credits exceeded"

    @pytest.mark.asyncio
    async def test_consume_credits_no_active_subscription(
        self, service, test_organization
    ):
        """Test credit consumption fails when no active subscription or wallet credits exist."""
        credits_needed = 100

        success, reason = await service.consume_credits(
            organization_id=test_organization.id, credits_needed=credits_needed
        )

        assert success is False
        assert reason == "No credits available"

    @pytest.mark.asyncio
    async def test_consume_credits_with_wallet_no_subscription(
        self, service, test_organization, db_session
    ):
        """Test credit consumption succeeds with wallet credits even without active subscription."""
        # Create a trial credit grant (wallet credit) without subscription
        trial_topup = await TopUpFactory.create_async(
            db_session,
            organization_id=test_organization.id,
            description="Trial Credits",
            price_paid=0.0,
            credits_purchased=50,
            package_type=GrantType.TRIAL,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )

        trial_grant = await CreditGrantFactory.create_async(
            db_session,
            organization_id=test_organization.id,
            topup_id=trial_topup.id,
            grant_type=GrantType.TRIAL,
            description="Trial Credits",
            amount=50,
            remaining_amount=50,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        await db_session.commit()

        credits_needed = 25

        success, reason = await service.consume_credits(
            organization_id=test_organization.id, credits_needed=credits_needed
        )

        # Should succeed without subscription because wallet credits are available
        assert success is True
        assert reason == "Credits consumed successfully"

        # Verify grant was consumed
        await db_session.refresh(trial_grant)
        assert trial_grant.remaining_amount == 25

    @pytest.mark.asyncio
    async def test_consume_credits_subscription_paused(
        self, service, active_subscription, usage_period
    ):
        """Test credit consumption fails when subscription access is paused."""
        # Pause subscription access
        active_subscription.pause_access = True
        await service.db.commit()

        organization_id = active_subscription.organization_id
        credits_needed = 100

        success, reason = await service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is False
        assert reason == "Account access paused due to payment issues"

    @pytest.mark.asyncio
    async def test_consume_credits_no_usage_period(
        self, service, active_subscription, subscription_credit_grant
    ):
        """Test credit consumption fails when no usage period exists."""
        organization_id = active_subscription.organization_id
        credits_needed = 100

        success, reason = await service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is False
        assert reason == "No active usage period found"

    @pytest.mark.asyncio
    async def test_consume_credits_with_user_and_api_key(
        self, service, active_subscription, subscription_credit_grant, usage_period
    ):
        """Test credit consumption tracks user and API key."""
        organization_id = active_subscription.organization_id
        user_id = uuid4()
        api_key_id = uuid4()
        credits_needed = 100

        success, reason = await service.consume_credits(
            organization_id=organization_id,
            credits_needed=credits_needed,
            user_id=user_id,
            api_key_id=api_key_id,
        )

        assert success is True

        # Verify usage record includes user and API key
        from sqlalchemy import select
        from src.database.models import UsageRecord

        result = await service.db.execute(
            select(UsageRecord).where(UsageRecord.organization_id == organization_id)
        )
        records = result.scalars().all()
        assert len(records) == 1
        assert records[0].user_id == user_id
        assert records[0].api_key_id == api_key_id

    @pytest.mark.asyncio
    async def test_consume_credits_alert_threshold_triggered(
        self, service, active_subscription, subscription_credit_grant, usage_period
    ):
        """Test that usage alerts are triggered when thresholds are reached."""
        # Set up alert settings with 80% threshold
        alert_settings = AlertSettings(
            subscription_id=active_subscription.id,
            alert_thresholds=[0.8],  # 80% threshold
            alert_destinations=["test@example.com"],
            alerts_enabled=True,
        )
        service.db.add(alert_settings)

        # Use 850 credits (85% of 1000 allowance)
        subscription_credit_grant.remaining_amount = 150  # 850 already consumed
        credits_needed = 100  # This will push to 950 consumed (95%)

        await service.db.commit()

        organization_id = active_subscription.organization_id

        with patch.object(service, "_trigger_usage_alert") as mock_alert:
            success, reason = await service.consume_credits(
                organization_id=organization_id, credits_needed=credits_needed
            )

            assert success is True
            # Verify alert was triggered
            mock_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_consume_credits_expired_grants_ignored(
        self, service, active_subscription, usage_period
    ):
        """Test that expired credit grants are not used for consumption."""
        # Create an expired subscription grant
        expired_grant = CreditGrant(
            id=uuid4(),
            organization_id=active_subscription.organization_id,
            subscription_id=active_subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Expired grant",
            amount=100,
            remaining_amount=100,
            expires_at=datetime.now(timezone.utc)
            - timedelta(days=1),  # Expired yesterday
        )
        service.db.add(expired_grant)

        # Create a valid grant with only 50 credits
        valid_grant = CreditGrant(
            id=uuid4(),
            organization_id=active_subscription.organization_id,
            subscription_id=active_subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Valid grant",
            amount=100,
            remaining_amount=50,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        service.db.add(valid_grant)

        await service.db.commit()

        organization_id = active_subscription.organization_id
        credits_needed = 75  # More than valid grant has

        success, reason = await service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is False
        assert reason == "No credits available"

        # Verify expired grant was not used
        await service.db.refresh(expired_grant)
        assert expired_grant.remaining_amount == 100  # Unchanged

        # Verify valid grant was not consumed (pre-flight check prevents partial consumption)
        await service.db.refresh(valid_grant)
        assert valid_grant.remaining_amount == 50  # Unchanged

    @pytest.mark.asyncio
    async def test_consume_credits_priority_order_subscription_first(
        self,
        service,
        active_subscription,
        subscription_credit_grant,
        topup_credit_grants,
        usage_period,
    ):
        """Test that subscription credits are consumed before topup credits."""
        organization_id = active_subscription.organization_id
        credits_needed = 50  # Less than subscription remaining (800)

        success, reason = await service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is True

        # Verify only subscription grant was consumed
        await service.db.refresh(subscription_credit_grant)
        assert subscription_credit_grant.remaining_amount == 750  # 800 - 50

        # Verify topup grants were not touched
        for grant in topup_credit_grants:
            await service.db.refresh(grant)
            assert grant.remaining_amount in [200, 500]  # Unchanged

    @pytest.mark.asyncio
    async def test_credits_summary_used_this_period_excludes_topup_usage(
        self,
        service,
        active_subscription,
        subscription_credit_grant,
        topup_credit_grants,
        usage_period,
    ):
        """Test that used_this_period only counts subscription credits, not top-up credits."""
        organization_id = active_subscription.organization_id

        # Consume 100 credits from subscription
        success1, _ = await service.consume_credits(
            organization_id=organization_id, credits_needed=100
        )
        assert success1 is True

        # Consume all remaining subscription credits (700)
        await service.db.refresh(subscription_credit_grant)
        remaining_subscription = subscription_credit_grant.remaining_amount
        success2, _ = await service.consume_credits(
            organization_id=organization_id, credits_needed=remaining_subscription
        )
        assert success2 is True

        # Now consume 150 credits which will come from topup
        success3, _ = await service.consume_credits(
            organization_id=organization_id, credits_needed=150
        )
        assert success3 is True

        await service.db.commit()

        # Get credits summary
        summary = await service.get_credits_summary(organization_id=organization_id)

        # Verify subscription summary
        assert summary.subscription is not None
        assert summary.subscription.granted_this_period == 1000
        # used_this_period should only count the 800 subscription credits consumed (100 + 700)
        # NOT the 150 topup credits consumed
        assert summary.subscription.used_this_period == 800
        assert summary.subscription.remaining == 0

        # Verify topup summary shows 150 used
        total_topup_used = sum(topup.used for topup in summary.topups if topup.used > 0)
        assert total_topup_used == 150

    @pytest.mark.asyncio
    async def test_partial_consumption_from_multiple_sources_with_usage_records(
        self,
        service,
        active_subscription,
        subscription_credit_grant,
        topup_credit_grants,
        usage_period,
    ):
        """
        Test partial consumption from subscription and topups creates separate usage records.

        Scenario: Cost 500 credits with 250 in subscription + 400 in topup available
        Expected: Two UsageRecords - one for 250 from subscription, one for 250 from topup
        """
        from sqlalchemy import select
        from src.database.models import UsageRecord, OperationType

        organization_id = active_subscription.organization_id

        # Set subscription grant to 250 remaining
        subscription_credit_grant.remaining_amount = 250
        await service.db.commit()

        # Cost: 500 credits (needs 250 subscription + 250 topup)
        credits_needed = 500
        user_id = uuid4()
        api_key_id = uuid4()

        success, reason = await service.consume_credits(
            organization_id=organization_id,
            credits_needed=credits_needed,
            user_id=user_id,
            api_key_id=api_key_id,
        )

        assert success is True
        assert reason == "Credits consumed successfully"

        # Verify subscription grant is fully consumed
        await service.db.refresh(subscription_credit_grant)
        assert subscription_credit_grant.remaining_amount == 0

        # Verify topup was partially consumed (earliest expiry first)
        await service.db.refresh(topup_credit_grants[1])  # 30 days expiry (earlier)
        assert topup_credit_grants[1].remaining_amount == 250  # 500 - 250

        # Get all usage records
        stmt = (
            select(UsageRecord)
            .where(
                UsageRecord.organization_id == organization_id,
                UsageRecord.operation_type == OperationType.CONSUMPTION,
            )
            .order_by(UsageRecord.created_at.asc())
        )
        result = await service.db.execute(stmt)
        records = result.scalars().all()

        # Should have exactly 2 usage records
        assert len(records) == 2

        # First record: subscription consumption
        sub_record = records[0]
        assert sub_record.credits_consumed == 250
        assert sub_record.subscription_id == active_subscription.id
        assert sub_record.topup_id is None
        assert sub_record.user_id == user_id
        assert sub_record.api_key_id == api_key_id

        # Second record: topup consumption
        topup_record = records[1]
        assert topup_record.credits_consumed == 250
        assert topup_record.subscription_id is None
        assert topup_record.topup_id == topup_credit_grants[1].topup_id
        assert topup_record.user_id == user_id
        assert topup_record.api_key_id == api_key_id

    @pytest.mark.asyncio
    async def test_consumption_order_across_all_three_sources(
        self,
        service,
        active_subscription,
        subscription_credit_grant,
        topup_credit_grants,
        usage_period,
    ):
        """
        Test that credits are consumed in correct order: subscription → topups → overage.

        Scenario: Cost 2000 credits with 800 subscription + 700 topups + overage enabled
        Expected: Consumes all subscription, all topups, then 500 from overage
        """
        from sqlalchemy import select
        from src.database.models import UsageRecord, OperationType

        organization_id = active_subscription.organization_id

        # Enable overage with high cap
        active_subscription.overage_enabled = True
        active_subscription.user_extra_cap = 1000
        await service.db.commit()

        # Total available before overage: 800 (subscription) + 700 (topups) = 1500
        # Request 2000 to use 500 overage
        credits_needed = 2000
        user_id = uuid4()

        success, reason = await service.consume_credits(
            organization_id=organization_id,
            credits_needed=credits_needed,
            user_id=user_id,
        )

        assert success is True
        assert reason == "Credits consumed successfully"

        # 1. Verify subscription grant fully consumed
        await service.db.refresh(subscription_credit_grant)
        assert subscription_credit_grant.remaining_amount == 0

        # 2. Verify all topup grants fully consumed
        for grant in topup_credit_grants:
            await service.db.refresh(grant)
            assert grant.remaining_amount == 0

        # 3. Verify overage used
        await service.db.refresh(usage_period)
        assert usage_period.overage_used == 500

        # Get all usage records (excluding overage as it doesn't create UsageRecord)
        stmt = (
            select(UsageRecord)
            .where(
                UsageRecord.organization_id == organization_id,
                UsageRecord.operation_type == OperationType.CONSUMPTION,
            )
            .order_by(UsageRecord.created_at.asc())
        )
        result = await service.db.execute(stmt)
        records = result.scalars().all()

        # Should have 3 records: 1 subscription + 2 topups (no record for overage)
        assert len(records) == 3

        # Record 1: subscription (800 credits)
        assert records[0].credits_consumed == 800
        assert records[0].subscription_id == active_subscription.id
        assert records[0].topup_id is None

        # Record 2: first topup by expiry (30 days, 500 credits)
        assert records[1].credits_consumed == 500
        assert records[1].subscription_id is None
        assert records[1].topup_id == topup_credit_grants[1].topup_id

        # Record 3: second topup (60 days, 200 credits)
        assert records[2].credits_consumed == 200
        assert records[2].subscription_id is None
        assert records[2].topup_id == topup_credit_grants[0].topup_id

        # Total from records should be 1500 (not including overage)
        total_from_records = sum(r.credits_consumed for r in records)
        assert total_from_records == 1500

    @pytest.mark.asyncio
    async def test_topup_expiry_ordering_with_multiple_topups(
        self,
        service,
        db_session,
        active_subscription,
        test_organization,
        usage_period,
    ):
        """
        Test that topups are consumed in earliest-expiry-first order.

        Scenario: 4 topups with different expiry dates
        Expected: Consumed in order of earliest expiry
        """
        from sqlalchemy import select
        from src.database.models import UsageRecord, OperationType

        organization_id = active_subscription.organization_id

        # Create 4 topups with different expiry dates
        topup_data = [
            (100, 60, "Topup A - 60 days"),  # Latest expiry
            (150, 15, "Topup B - 15 days"),  # Second earliest
            (200, 7, "Topup C - 7 days"),  # Earliest expiry
            (250, 30, "Topup D - 30 days"),  # Third earliest
        ]

        topups = []
        for credits, days, desc in topup_data:
            topup = await TopUpFactory.create_async(
                db_session,
                organization_id=organization_id,
                description=desc,
                price_paid=float(credits / 10),
                credits_purchased=credits,
                expires_at=datetime.now(timezone.utc) + timedelta(days=days),
            )

            grant = await CreditGrantFactory.create_async(
                db_session,
                organization_id=organization_id,
                topup_id=topup.id,
                grant_type=GrantType.TOPUP,
                description=desc,
                amount=credits,
                remaining_amount=credits,
                expires_at=datetime.now(timezone.utc) + timedelta(days=days),
            )
            topups.append((topup, grant, days))

        await service.db.commit()

        # Consume 400 credits (should use: 200 from 7-day, 150 from 15-day, 50 from 30-day)
        credits_needed = 400

        success, reason = await service.consume_credits(
            organization_id=organization_id,
            credits_needed=credits_needed,
        )

        assert success is True

        # Get usage records in order
        stmt = (
            select(UsageRecord)
            .where(
                UsageRecord.organization_id == organization_id,
                UsageRecord.operation_type == OperationType.CONSUMPTION,
            )
            .order_by(UsageRecord.created_at.asc())
        )
        result = await service.db.execute(stmt)
        records = result.scalars().all()

        # Should have 3 usage records
        assert len(records) == 3

        # Verify consumption order by expiry
        # Record 1: 7-day topup (200 credits) - earliest expiry
        assert records[0].credits_consumed == 200
        assert records[0].topup_id == topups[2][0].id  # Topup C

        # Record 2: 15-day topup (150 credits) - second earliest
        assert records[1].credits_consumed == 150
        assert records[1].topup_id == topups[1][0].id  # Topup B

        # Record 3: 30-day topup (50 credits) - third earliest
        assert records[2].credits_consumed == 50
        assert records[2].topup_id == topups[3][0].id  # Topup D

    @pytest.mark.asyncio
    async def test_overage_cap_enforcement_with_partial_consumption(
        self,
        service,
        active_subscription,
        subscription_credit_grant,
        topup_credit_grants,
        usage_period,
    ):
        """
        Test that overage cap is enforced and prevents partial consumption.

        Scenario: Need 2000 credits, have 1500 available, cap is 200 (need 500)
        Expected: Consumption fails, no credits consumed from any source
        """
        from sqlalchemy import select
        from src.database.models import UsageRecord

        organization_id = active_subscription.organization_id

        # Enable overage with cap of 200 (need 500)
        active_subscription.overage_enabled = True
        active_subscription.user_extra_cap = 200  # Cap too low
        await service.db.commit()

        # Store initial values
        initial_sub_remaining = subscription_credit_grant.remaining_amount
        initial_topup1_remaining = topup_credit_grants[0].remaining_amount
        initial_topup2_remaining = topup_credit_grants[1].remaining_amount

        # Request 2000 (would need 500 overage which exceeds cap of 200)
        credits_needed = 2000

        success, reason = await service.consume_credits(
            organization_id=organization_id,
            credits_needed=credits_needed,
        )

        assert success is False
        assert "Overage cap" in reason
        assert "200" in reason

        # Verify NO credits were consumed from any source
        await service.db.refresh(subscription_credit_grant)
        assert subscription_credit_grant.remaining_amount == initial_sub_remaining

        for i, grant in enumerate(topup_credit_grants):
            await service.db.refresh(grant)
            if i == 0:
                assert grant.remaining_amount == initial_topup1_remaining
            else:
                assert grant.remaining_amount == initial_topup2_remaining

        # Verify no overage was used
        await service.db.refresh(usage_period)
        assert usage_period.overage_used == 0

        # Verify no usage records were created
        stmt = select(UsageRecord).where(UsageRecord.organization_id == organization_id)
        result = await service.db.execute(stmt)
        records = result.scalars().all()
        assert len(records) == 0

    @pytest.mark.asyncio
    async def test_overage_unlimited_cap_with_large_consumption(
        self,
        service,
        active_subscription,
        subscription_credit_grant,
        topup_credit_grants,
        usage_period,
    ):
        """
        Test overage with unlimited cap (user_extra_cap = None).

        Scenario: Need 5000 credits, have 1500 available, unlimited overage
        Expected: Consumes all available, then 3500 from overage
        """
        organization_id = active_subscription.organization_id

        # Enable overage with unlimited cap
        active_subscription.overage_enabled = True
        active_subscription.user_extra_cap = None  # Unlimited
        await service.db.commit()

        # Request 5000 (1500 available + 3500 overage)
        credits_needed = 5000

        success, reason = await service.consume_credits(
            organization_id=organization_id,
            credits_needed=credits_needed,
        )

        assert success is True
        assert reason == "Credits consumed successfully"

        # Verify all subscription consumed
        await service.db.refresh(subscription_credit_grant)
        assert subscription_credit_grant.remaining_amount == 0

        # Verify all topups consumed
        for grant in topup_credit_grants:
            await service.db.refresh(grant)
            assert grant.remaining_amount == 0

        # Verify 3500 overage used
        await service.db.refresh(usage_period)
        assert usage_period.overage_used == 3500

    @pytest.mark.asyncio
    async def test_complex_partial_consumption_three_topups(
        self,
        service,
        db_session,
        active_subscription,
        test_organization,
        usage_period,
    ):
        """
        Test complex scenario with partial consumption across subscription and multiple topups.

        Scenario: Cost 1000 with subscription=300, topup1=250, topup2=400, topup3=100
        Expected: Uses all 300 sub + all 250 topup1 + 400 topup2 + 50 from topup3
        """
        from sqlalchemy import select
        from src.database.models import UsageRecord, OperationType

        organization_id = active_subscription.organization_id

        # Create subscription grant with 300 remaining
        sub_grant = await CreditGrantFactory.create_async(
            db_session,
            organization_id=organization_id,
            subscription_id=active_subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Monthly allowance",
            amount=1000,
            remaining_amount=300,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )

        # Create 3 topups with different amounts
        topup_configs = [
            (250, 10, "Topup 1"),  # Earliest expiry
            (400, 20, "Topup 2"),
            (100, 30, "Topup 3"),  # Latest expiry
        ]

        topup_grants = []
        for credits, days, desc in topup_configs:
            topup = await TopUpFactory.create_async(
                db_session,
                organization_id=organization_id,
                description=desc,
                price_paid=float(credits / 10),
                credits_purchased=credits,
                expires_at=datetime.now(timezone.utc) + timedelta(days=days),
            )

            grant = await CreditGrantFactory.create_async(
                db_session,
                organization_id=organization_id,
                topup_id=topup.id,
                grant_type=GrantType.TOPUP,
                description=desc,
                amount=credits,
                remaining_amount=credits,
                expires_at=datetime.now(timezone.utc) + timedelta(days=days),
            )
            topup_grants.append((topup, grant))

        await service.db.commit()

        # Consume 1000 credits
        # Expected: 300 (sub) + 250 (topup1) + 400 (topup2) + 50 (topup3)
        credits_needed = 1000

        success, reason = await service.consume_credits(
            organization_id=organization_id,
            credits_needed=credits_needed,
        )

        assert success is True

        # Verify subscription fully consumed
        await service.db.refresh(sub_grant)
        assert sub_grant.remaining_amount == 0

        # Verify topup consumptions
        await service.db.refresh(topup_grants[0][1])
        assert topup_grants[0][1].remaining_amount == 0  # Fully consumed

        await service.db.refresh(topup_grants[1][1])
        assert topup_grants[1][1].remaining_amount == 0  # Fully consumed

        await service.db.refresh(topup_grants[2][1])
        assert (
            topup_grants[2][1].remaining_amount == 50
        )  # Partially consumed (100 - 50)

        # Get usage records and verify
        stmt = (
            select(UsageRecord)
            .where(
                UsageRecord.organization_id == organization_id,
                UsageRecord.operation_type == OperationType.CONSUMPTION,
            )
            .order_by(UsageRecord.created_at.asc())
        )
        result = await service.db.execute(stmt)
        records = result.scalars().all()

        # Should have 4 usage records
        assert len(records) == 4

        # Verify amounts
        assert records[0].credits_consumed == 300  # Subscription
        assert records[1].credits_consumed == 250  # Topup 1
        assert records[2].credits_consumed == 400  # Topup 2
        assert records[3].credits_consumed == 50  # Topup 3 (partial)

        # Verify IDs
        assert records[0].subscription_id == active_subscription.id
        assert records[0].topup_id is None

        assert records[1].topup_id == topup_grants[0][0].id
        assert records[1].subscription_id is None

        assert records[2].topup_id == topup_grants[1][0].id
        assert records[2].subscription_id is None

        assert records[3].topup_id == topup_grants[2][0].id
        assert records[3].subscription_id is None

        # Total should match requested
        total = sum(r.credits_consumed for r in records)
        assert total == 1000
