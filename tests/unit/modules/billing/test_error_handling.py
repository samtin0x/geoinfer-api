"""Error handling and edge case tests."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from uuid import uuid4

from src.database.models import (
    Subscription,
    SubscriptionStatus,
    CreditGrant,
    GrantType,
    UsagePeriod,
    PlanTier,
)
from src.database.models.alerts import AlertSettings
from src.modules.billing.credits.service import CreditConsumptionService
from tests.factories import OrganizationFactory, SubscriptionFactory


class TestErrorHandling:
    """Test suite for error handling and edge cases."""

    @pytest.fixture
    def consumption_service(self, db_session):
        """Create credit consumption service instance."""
        return CreditConsumptionService(db_session)

    @pytest_asyncio.fixture
    async def test_organization(self, db_session):
        """Create a test organization."""
        return await OrganizationFactory.create_async(
            db_session,
            plan_tier=PlanTier.SUBSCRIBED,
            name="Test Organization",
        )

    @pytest_asyncio.fixture
    async def subscription_with_issues(self, db_session, test_organization):
        """Create a subscription with various issues."""
        return await SubscriptionFactory.create_async(
            db_session,
            organization_id=test_organization.id,
            stripe_subscription_id="sub_issues_123",
            stripe_customer_id="cus_issues_456",
            description="Problematic Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.PAST_DUE,
            overage_enabled=False,
            pause_access=True,  # Access paused due to payment issues
            current_period_start=datetime.now(timezone.utc) - timedelta(days=30),
            current_period_end=datetime.now(timezone.utc)
            - timedelta(days=1),  # Expired
        )

    @pytest.mark.asyncio
    async def test_credit_consumption_with_past_due_subscription(
        self, consumption_service, subscription_with_issues
    ):
        """Test credit consumption fails with past due subscription."""
        # Create an expired credit grant
        grant = CreditGrant(
            id=uuid4(),
            organization_id=subscription_with_issues.organization_id,
            subscription_id=subscription_with_issues.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Expired allowance",
            amount=1000,
            remaining_amount=500,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),  # Expired
        )
        consumption_service.db.add(grant)
        await consumption_service.db.commit()

        credits_needed = 100

        success, reason = await consumption_service.consume_credits(
            organization_id=subscription_with_issues.organization_id,
            credits_needed=credits_needed,
        )

        assert success is False
        assert "Account access paused due to payment issues" in reason

    @pytest.mark.asyncio
    async def test_credit_consumption_with_expired_period(
        self, consumption_service, subscription_with_issues
    ):
        """Test credit consumption fails with expired subscription period."""
        # Create a valid credit grant but expired period
        grant = CreditGrant(
            id=uuid4(),
            organization_id=subscription_with_issues.organization_id,
            subscription_id=subscription_with_issues.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Valid grant but expired period",
            amount=1000,
            remaining_amount=500,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),  # Valid expiry
        )
        consumption_service.db.add(grant)

        # Create a closed usage period (expired)
        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription_with_issues.id,
            period_start=datetime.now(timezone.utc) - timedelta(days=30),
            period_end=datetime.now(timezone.utc) - timedelta(days=1),
            overage_used=0,
            overage_reported=0,
            closed=True,  # Closed/expired
        )
        consumption_service.db.add(usage_period)
        await consumption_service.db.commit()

        credits_needed = 100

        success, reason = await consumption_service.consume_credits(
            organization_id=subscription_with_issues.organization_id,
            credits_needed=credits_needed,
        )

        assert success is False
        assert "No active usage period found" in reason

    @pytest.mark.asyncio
    async def test_credit_consumption_database_connection_error(
        self, consumption_service, test_organization
    ):
        """Test credit consumption handles database connection errors."""
        # Create a valid subscription and grant
        subscription = Subscription(
            id=uuid4(),
            organization_id=test_organization.id,
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(subscription)

        grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            subscription_id=subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Monthly allowance",
            amount=1000,
            remaining_amount=1000,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(grant)

        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30),
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        consumption_service.db.add(usage_period)
        await consumption_service.db.commit()

        # Mock database error during consumption
        with patch.object(consumption_service.db, "commit") as mock_commit:
            mock_commit.side_effect = Exception("Database connection lost")

            credits_needed = 100

            success, reason = await consumption_service.consume_credits(
                organization_id=test_organization.id, credits_needed=credits_needed
            )

            # Should handle database errors gracefully
            assert success is False
            assert "Database connection lost" in reason

    @pytest.mark.asyncio
    async def test_credit_consumption_negative_amount(
        self, consumption_service, test_organization
    ):
        """Test credit consumption handles negative credit amounts."""
        subscription = Subscription(
            id=uuid4(),
            organization_id=test_organization.id,
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(subscription)

        grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            subscription_id=subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Monthly allowance",
            amount=1000,
            remaining_amount=1000,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(grant)

        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30),
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        consumption_service.db.add(usage_period)
        await consumption_service.db.commit()

        # Try to consume negative credits
        success, reason = await consumption_service.consume_credits(
            organization_id=test_organization.id, credits_needed=-100  # Negative amount
        )

        assert success is False
        assert "Invalid credit amount" in reason or "negative" in reason.lower()

    @pytest.mark.asyncio
    async def test_credit_consumption_zero_amount(
        self, consumption_service, test_organization
    ):
        """Test credit consumption handles zero credit amounts."""
        subscription = Subscription(
            id=uuid4(),
            organization_id=test_organization.id,
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(subscription)

        grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            subscription_id=subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Monthly allowance",
            amount=1000,
            remaining_amount=1000,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(grant)

        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30),
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        consumption_service.db.add(usage_period)
        await consumption_service.db.commit()

        # Try to consume zero credits
        success, reason = await consumption_service.consume_credits(
            organization_id=test_organization.id, credits_needed=0
        )

        assert success is False
        assert "Invalid credit amount" in reason or "zero" in reason.lower()

    @pytest.mark.asyncio
    async def test_credit_consumption_extremely_large_amount(
        self, consumption_service, test_organization
    ):
        """Test credit consumption handles extremely large credit amounts."""
        subscription = Subscription(
            id=uuid4(),
            organization_id=test_organization.id,
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            overage_enabled=True,
            user_extra_cap=10000,  # Large cap
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(subscription)

        grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            subscription_id=subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Monthly allowance",
            amount=1000,
            remaining_amount=1000,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(grant)

        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30),
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        consumption_service.db.add(usage_period)
        await consumption_service.db.commit()

        # Try to consume extremely large amount
        credits_needed = 10**9  # 1 billion credits

        success, reason = await consumption_service.consume_credits(
            organization_id=test_organization.id, credits_needed=credits_needed
        )

        # Should fail due to overage cap or insufficient credits
        assert success is False
        assert "exceeded" in reason.lower() or "insufficient" in reason.lower()

    @pytest.mark.asyncio
    async def test_credit_consumption_concurrent_access(
        self, consumption_service, test_organization
    ):
        """Test credit consumption handles concurrent access scenarios."""
        subscription = Subscription(
            id=uuid4(),
            organization_id=test_organization.id,
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(subscription)

        grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            subscription_id=subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Monthly allowance",
            amount=1000,
            remaining_amount=1000,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(grant)

        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30),
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        consumption_service.db.add(usage_period)
        await consumption_service.db.commit()

        # Simulate concurrent access by trying to consume more than available
        # First consumption should succeed
        success1, reason1 = await consumption_service.consume_credits(
            organization_id=test_organization.id, credits_needed=600
        )
        assert success1 is True

        # Second consumption should fail due to insufficient credits
        success2, reason2 = await consumption_service.consume_credits(
            organization_id=test_organization.id,
            credits_needed=600,  # More than remaining
        )
        assert success2 is False
        assert "insufficient" in reason2.lower() or "overage" in reason2.lower()

    @pytest.mark.asyncio
    async def test_credit_consumption_expired_grants_cleanup(
        self, consumption_service, test_organization
    ):
        """Test that expired grants are properly handled during consumption."""
        subscription = Subscription(
            id=uuid4(),
            organization_id=test_organization.id,
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(subscription)

        # Create expired grant
        expired_grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            subscription_id=subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Expired grant",
            amount=1000,
            remaining_amount=500,
            expires_at=datetime.now(timezone.utc)
            - timedelta(days=1),  # Expired yesterday
        )
        consumption_service.db.add(expired_grant)

        # Create valid grant with only 100 credits
        valid_grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            subscription_id=subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Valid grant",
            amount=100,
            remaining_amount=100,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(valid_grant)

        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30),
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        consumption_service.db.add(usage_period)
        await consumption_service.db.commit()

        # Try to consume more than available valid credits
        credits_needed = 150

        success, reason = await consumption_service.consume_credits(
            organization_id=test_organization.id, credits_needed=credits_needed
        )

        assert success is False
        assert "insufficient" in reason.lower() or "overage" in reason.lower()

        # Verify expired grant was not consumed
        await consumption_service.db.refresh(expired_grant)
        assert expired_grant.remaining_amount == 500  # Unchanged

        # Verify valid grant was fully consumed
        await consumption_service.db.refresh(valid_grant)
        assert valid_grant.remaining_amount == 0

    @pytest.mark.asyncio
    async def test_credit_consumption_rollback_on_error(
        self, consumption_service, test_organization
    ):
        """Test that credit consumption rolls back properly on errors."""
        subscription = Subscription(
            id=uuid4(),
            organization_id=test_organization.id,
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(subscription)

        grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            subscription_id=subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Monthly allowance",
            amount=1000,
            remaining_amount=1000,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(grant)

        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30),
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        consumption_service.db.add(usage_period)
        await consumption_service.db.commit()

        # Mock an error during the commit phase
        original_remaining = grant.remaining_amount

        with patch.object(consumption_service.db, "commit") as mock_commit:
            mock_commit.side_effect = Exception("Database error during commit")

            success, reason = await consumption_service.consume_credits(
                organization_id=test_organization.id, credits_needed=100
            )

            # Should fail due to commit error
            assert success is False
            assert "Database error during commit" in reason

            # Verify no credits were actually consumed (rollback worked)
            await consumption_service.db.refresh(grant)
            assert grant.remaining_amount == original_remaining

    @pytest.mark.asyncio
    async def test_credit_consumption_alert_error_handling(
        self, consumption_service, test_organization
    ):
        """Test that credit consumption continues even if alert sending fails."""
        subscription = Subscription(
            id=uuid4(),
            organization_id=test_organization.id,
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(subscription)

        grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            subscription_id=subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Monthly allowance",
            amount=1000,
            remaining_amount=100,  # 900 consumed - should trigger alert at 90%
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(grant)

        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30),
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        consumption_service.db.add(usage_period)

        # Create alert settings that would trigger
        alert_settings = AlertSettings(
            subscription_id=subscription.id,
            alert_thresholds=[0.9],  # 90% threshold
            alert_destinations=["admin@example.com"],
            alerts_enabled=True,
        )
        consumption_service.db.add(alert_settings)
        await consumption_service.db.commit()

        # Mock alert triggering to fail
        with patch.object(consumption_service, "_trigger_usage_alert") as mock_alert:
            mock_alert.side_effect = Exception("Email service unavailable")

            # Consumption should still succeed even if alert fails
            success, reason = await consumption_service.consume_credits(
                organization_id=test_organization.id,
                credits_needed=100,  # This should trigger the 90% alert
            )

            assert success is True
            assert reason == "Credits consumed successfully"

            # Verify alert was attempted but failed
            mock_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_credit_consumption_memory_issues(
        self, consumption_service, test_organization
    ):
        """Test credit consumption handles memory-related issues."""
        subscription = Subscription(
            id=uuid4(),
            organization_id=test_organization.id,
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(subscription)

        # Create a very large number of credit grants to test memory handling
        grants = []
        for i in range(100):  # Create 100 grants
            grant = CreditGrant(
                id=uuid4(),
                organization_id=test_organization.id,
                subscription_id=subscription.id,
                grant_type=GrantType.TOPUP,
                description=f"Topup grant {i}",
                amount=10,
                remaining_amount=10,
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
            consumption_service.db.add(grant)
            grants.append(grant)

        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30),
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        consumption_service.db.add(usage_period)
        await consumption_service.db.commit()

        # Try to consume credits - should handle large number of grants
        credits_needed = 500

        success, reason = await consumption_service.consume_credits(
            organization_id=test_organization.id, credits_needed=credits_needed
        )

        # Should succeed and handle all grants properly
        assert success is True
        assert reason == "Credits consumed successfully"

        # Verify all grants were processed correctly
        total_consumed = 0
        for grant in grants:
            await consumption_service.db.refresh(grant)
            consumed = 10 - grant.remaining_amount
            total_consumed += consumed

        # Should have consumed 500 credits total (50 grants * 10 credits each)
        assert total_consumed == 500

    @pytest.mark.asyncio
    async def test_credit_consumption_malformed_data(
        self, consumption_service, test_organization
    ):
        """Test credit consumption handles malformed input data."""
        # Test with None organization_id
        success, reason = await consumption_service.consume_credits(
            organization_id=None, credits_needed=100
        )

        assert success is False
        assert "organization_id" in reason.lower() or "None" in reason.lower()

        # Test with None credits_needed
        success, reason = await consumption_service.consume_credits(
            organization_id=test_organization.id, credits_needed=None
        )

        assert success is False
        assert "credits_needed" in reason.lower() or "None" in reason.lower()

        # Test with string credits_needed
        success, reason = await consumption_service.consume_credits(
            organization_id=test_organization.id, credits_needed="invalid"
        )

        assert success is False
        assert "invalid" in reason.lower() or "type" in reason.lower()
