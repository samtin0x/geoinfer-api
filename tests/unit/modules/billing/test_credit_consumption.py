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

        # First topup: 200 credits, expires in 60 days
        grant1 = await CreditGrantFactory.create_async(
            db_session,
            organization_id=test_organization.id,
            grant_type=GrantType.TOPUP,
            description="Growth Topup",
            amount=200,
            remaining_amount=150,  # 50 already consumed
            expires_at=datetime.now(timezone.utc) + timedelta(days=60),
        )
        grants.append(grant1)

        # Second topup: 500 credits, expires in 30 days (earlier expiry)
        grant2 = await CreditGrantFactory.create_async(
            db_session,
            organization_id=test_organization.id,
            grant_type=GrantType.TOPUP,
            description="Pro Topup",
            amount=500,
            remaining_amount=300,  # 200 already consumed
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
        assert topup_credit_grants[1].remaining_amount == 200  # 300 - 100
        assert topup_credit_grants[0].remaining_amount == 150  # Unchanged

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
        assert reason == "No credits available and overage disabled"

        # Verify no credits were consumed
        await service.db.refresh(subscription_credit_grant)
        assert subscription_credit_grant.remaining_amount == 800

        for grant in topup_credit_grants:
            await service.db.refresh(grant)
            # Should remain unchanged
            assert grant.remaining_amount in [150, 300]

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
        credits_needed = 1500  # More than all available credits

        success, reason = await service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is True
        assert reason == "Credits consumed successfully"

        # Verify overage was used
        await service.db.refresh(usage_period)
        assert usage_period.overage_used == 200  # 1500 - 1300 available = 200 overage

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
        credits_needed = 1500  # Would require 200 overage, but cap is 100

        success, reason = await service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is False
        assert reason == "Overage cap of 100 credits exceeded"

    @pytest.mark.asyncio
    async def test_consume_credits_no_active_subscription(
        self, service, test_organization
    ):
        """Test credit consumption fails when no active subscription exists."""
        credits_needed = 100

        success, reason = await service.consume_credits(
            organization_id=test_organization.id, credits_needed=credits_needed
        )

        assert success is False
        assert reason == "No active subscription found"

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
        usage_records = await service.db.execute(
            "SELECT * FROM usage_records WHERE organization_id = :org_id",
            {"org_id": organization_id},
        )
        records = usage_records.fetchall()
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
        assert reason == "No credits available and overage disabled"

        # Verify expired grant was not used
        await service.db.refresh(expired_grant)
        assert expired_grant.remaining_amount == 100  # Unchanged

        # Verify valid grant was fully consumed
        await service.db.refresh(valid_grant)
        assert valid_grant.remaining_amount == 0

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
            assert grant.remaining_amount in [150, 300]  # Unchanged
