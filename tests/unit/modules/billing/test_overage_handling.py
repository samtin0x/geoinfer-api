"""Overage handling and billing tests."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from src.database.models import (
    Subscription,
    SubscriptionStatus,
    GrantType,
    UsagePeriod,
    PlanTier,
)
from src.database.models.alerts import AlertSettings
from src.modules.billing.credits.service import CreditConsumptionService
from tests.factories import (
    OrganizationFactory,
    SubscriptionFactory,
    CreditGrantFactory,
    UsagePeriodFactory,
)


class TestOverageHandling:
    """Test suite for overage handling and billing."""

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
    async def subscription_with_overage(self, db_session, test_organization):
        """Create a subscription with overage enabled."""
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
            overage_enabled=True,
            user_extra_cap=500,  # Allow 500 overage credits
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )

    @pytest_asyncio.fixture
    async def subscription_credit_grant(self, db_session, subscription_with_overage):
        """Create a subscription credit grant."""
        return await CreditGrantFactory.create_async(
            db_session,
            organization_id=subscription_with_overage.organization_id,
            subscription_id=subscription_with_overage.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Monthly allowance",
            amount=1000,
            remaining_amount=100,  # 900 already consumed
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )

    @pytest_asyncio.fixture
    async def usage_period(self, db_session, subscription_with_overage):
        """Create a usage period."""
        return await UsagePeriodFactory.create_async(
            db_session,
            subscription_id=subscription_with_overage.id,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30),
            overage_used=50,  # Already used 50 overage credits
            overage_reported=50,
            closed=False,
        )

    @pytest.mark.asyncio
    async def test_overage_consumption_within_cap(
        self,
        consumption_service,
        subscription_with_overage,
        subscription_credit_grant,
        usage_period,
    ):
        """Test overage consumption when within cap."""
        organization_id = subscription_with_overage.organization_id
        credits_needed = 600  # Would require 500 overage (within 500 cap)

        success, reason = await consumption_service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is True
        assert reason == "Credits consumed successfully"

        # Verify overage was used
        await consumption_service.db.refresh(usage_period)
        assert usage_period.overage_used == 550  # 50 + 500

        # Verify subscription grant was fully consumed
        await consumption_service.db.refresh(subscription_credit_grant)
        assert subscription_credit_grant.remaining_amount == 0

    @pytest.mark.asyncio
    async def test_overage_consumption_exceeds_cap(
        self,
        consumption_service,
        subscription_with_overage,
        subscription_credit_grant,
        usage_period,
    ):
        """Test overage consumption fails when cap is exceeded."""
        organization_id = subscription_with_overage.organization_id
        credits_needed = 700  # Would require 600 overage (exceeds 500 cap)

        success, reason = await consumption_service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is False
        assert reason == "Overage cap of 500 credits exceeded"

        # Verify no additional overage was used
        await consumption_service.db.refresh(usage_period)
        assert usage_period.overage_used == 50  # Unchanged

    @pytest.mark.asyncio
    async def test_overage_consumption_overage_disabled(
        self,
        consumption_service,
        subscription_with_overage,
        subscription_credit_grant,
        usage_period,
    ):
        """Test overage consumption fails when overage is disabled."""
        # Disable overage
        subscription_with_overage.overage_enabled = False
        await consumption_service.db.commit()

        organization_id = subscription_with_overage.organization_id
        credits_needed = 600  # Would require overage

        success, reason = await consumption_service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is False
        assert reason == "No credits available and overage disabled"

        # Verify no overage was used
        await consumption_service.db.refresh(usage_period)
        assert usage_period.overage_used == 50  # Unchanged

    @pytest.mark.asyncio
    async def test_overage_cap_calculation_with_user_extra_cap(
        self, consumption_service, subscription_with_overage
    ):
        """Test overage cap calculation considers user extra cap."""
        # Test with user_extra_cap set
        subscription_with_overage.user_extra_cap = 300
        await consumption_service.db.commit()

        # The effective cap should be the minimum of user_extra_cap and configured max
        effective_cap = consumption_service._calculate_effective_cap(
            subscription_with_overage
        )
        assert effective_cap == 300  # user_extra_cap

    @pytest.mark.asyncio
    async def test_overage_cap_calculation_without_user_extra_cap(
        self, consumption_service, subscription_with_overage
    ):
        """Test overage cap calculation without user extra cap."""
        # Remove user extra cap
        subscription_with_overage.user_extra_cap = None
        await consumption_service.db.commit()

        # Should use configured max (5000)
        effective_cap = consumption_service._calculate_effective_cap(
            subscription_with_overage
        )
        assert effective_cap == 5000

    @pytest.mark.asyncio
    async def test_overage_cap_calculation_overage_disabled(
        self, consumption_service, subscription_with_overage
    ):
        """Test overage cap calculation when overage is disabled."""
        # Disable overage
        subscription_with_overage.overage_enabled = False
        await consumption_service.db.commit()

        effective_cap = consumption_service._calculate_effective_cap(
            subscription_with_overage
        )
        assert effective_cap == 0  # No overage allowed

    @pytest.mark.asyncio
    async def test_overage_billing_integration(
        self, consumption_service, subscription_with_overage, usage_period
    ):
        """Test overage billing integration."""
        # Use some overage
        usage_period.overage_used = 100
        usage_period.overage_reported = 50  # 50 unreported
        await consumption_service.db.commit()

        # Mock Stripe Billing Meters API
        with patch("stripe.billing.MeterEvent.create") as mock_meter_event:
            mock_meter_event.return_value = MagicMock(id="evt_test_123")

            # Report overage
            result = await consumption_service._report_overage_to_stripe(
                usage_period_id=usage_period.id,
                subscription_id=subscription_with_overage.id,
            )

            assert result["success"] is True

            # Verify meter event was created
            mock_meter_event.assert_called_once()
            call_args = mock_meter_event.call_args[1]

            assert call_args["event_name"] == "credit_overage"
            assert call_args["payload"]["value"] == "50"  # Unreported amount as string
            assert (
                call_args["payload"]["stripe_customer_id"]
                == subscription_with_overage.stripe_customer_id
            )

            # Verify overage_reported was updated
            await consumption_service.db.refresh(usage_period)
            assert usage_period.overage_reported == 100

    @pytest.mark.asyncio
    async def test_overage_usage_tracking(
        self,
        consumption_service,
        subscription_with_overage,
        subscription_credit_grant,
        usage_period,
    ):
        """Test that overage usage is properly tracked."""
        organization_id = subscription_with_overage.organization_id
        credits_needed = 1200  # Would require 200 overage

        success, reason = await consumption_service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is True

        # Verify overage usage was recorded
        await consumption_service.db.refresh(usage_period)
        assert usage_period.overage_used == 250  # 50 + 200

        # Verify no usage record was created for overage (overage isn't a grant)
        usage_records = await consumption_service.db.execute(
            "SELECT * FROM usage_records WHERE organization_id = :org_id",
            {"org_id": organization_id},
        )
        records = usage_records.fetchall()

        # Should only have records for subscription and any topup credits consumed
        # No record for overage usage itself
        subscription_consumed = 900  # 1000 - 100 remaining
        assert len(records) == 1  # Only subscription consumption
        assert records[0].credits_consumed == subscription_consumed

    @pytest.mark.asyncio
    async def test_overage_alert_triggering(
        self,
        consumption_service,
        subscription_with_overage,
        subscription_credit_grant,
        usage_period,
    ):
        """Test that overage usage triggers alerts."""
        # Set up alert settings
        alert_settings = AlertSettings(
            subscription_id=subscription_with_overage.id,
            alert_thresholds=[0.8],  # 80% threshold
            alert_destinations=["admin@example.com"],
            alerts_enabled=True,
        )
        consumption_service.db.add(alert_settings)

        # Use credits that would trigger overage
        organization_id = subscription_with_overage.organization_id
        credits_needed = 1200  # Would require 200 overage

        with patch.object(consumption_service, "_trigger_usage_alert") as mock_alert:
            success, reason = await consumption_service.consume_credits(
                organization_id=organization_id, credits_needed=credits_needed
            )

            assert success is True

            # Verify alert was triggered for overage usage
            mock_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_overage_reset_on_period_renewal(
        self, consumption_service, subscription_with_overage, usage_period
    ):
        """Test that overage counters are reset on period renewal."""
        # Set overage usage
        usage_period.overage_used = 100
        usage_period.overage_reported = 100
        await consumption_service.db.commit()

        # Simulate period renewal (new usage period creation)
        new_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription_with_overage.id,
            period_start=datetime.now(timezone.utc) + timedelta(days=30),
            period_end=datetime.now(timezone.utc) + timedelta(days=60),
            overage_used=0,  # Reset
            overage_reported=0,  # Reset
            closed=False,
        )
        consumption_service.db.add(new_period)
        await consumption_service.db.commit()

        # Verify new period has reset counters
        retrieved_new_period = await consumption_service.db.get(
            UsagePeriod, new_period.id
        )
        assert retrieved_new_period.overage_used == 0
        assert retrieved_new_period.overage_reported == 0

        # Verify old period counters unchanged
        retrieved_old_period = await consumption_service.db.get(
            UsagePeriod, usage_period.id
        )
        assert retrieved_old_period.overage_used == 100
        assert retrieved_old_period.overage_reported == 100

    @pytest.mark.asyncio
    async def test_overage_unit_price_calculation(
        self, consumption_service, subscription_with_overage
    ):
        """Test overage unit price is correctly applied."""
        # Use overage
        usage_period = await consumption_service._get_current_usage_period(
            subscription_with_overage.id
        )
        usage_period.overage_used = 100
        await consumption_service.db.commit()

        # Calculate expected cost
        expected_cost = (
            100 * subscription_with_overage.overage_unit_price
        )  # 100 credits * €0.06

        # Verify unit price is correctly stored
        assert subscription_with_overage.overage_unit_price == 0.06
        assert expected_cost == 6.00  # €6.00 for 100 credits

    @pytest.mark.asyncio
    async def test_overage_cap_enforcement_edge_cases(
        self,
        consumption_service,
        subscription_with_overage,
        subscription_credit_grant,
        usage_period,
    ):
        """Test edge cases for overage cap enforcement."""
        # Test exactly at cap
        organization_id = subscription_with_overage.organization_id
        credits_needed = 600  # Would require exactly 500 overage (at cap)

        success, reason = await consumption_service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is True  # Should succeed at exactly the cap

        # Test just over cap
        credits_needed = 601  # Would require 501 overage (1 over cap)

        success, reason = await consumption_service.consume_credits(
            organization_id=organization_id, credits_needed=credits_needed
        )

        assert success is False  # Should fail when exceeding cap
        assert "Overage cap of 500 credits exceeded" in reason

    @pytest.mark.asyncio
    async def test_overage_reporting_batch_processing(
        self, consumption_service, subscription_with_overage
    ):
        """Test batch processing of overage reporting."""
        # Create multiple usage periods with unreported overage
        periods_data = [
            (50, 25),  # 25 unreported
            (100, 75),  # 25 unreported
            (200, 150),  # 50 unreported
        ]

        periods = []
        for overage_used, overage_reported in periods_data:
            period = UsagePeriod(
                id=uuid4(),
                subscription_id=subscription_with_overage.id,
                period_start=datetime.now(timezone.utc),
                period_end=datetime.now(timezone.utc) + timedelta(days=30),
                overage_used=overage_used,
                overage_reported=overage_reported,
                closed=False,
            )
            consumption_service.db.add(period)
            periods.append(period)

        await consumption_service.db.commit()

        # Mock Stripe Billing Meters API
        with patch("stripe.billing.MeterEvent.create") as mock_meter_event:
            mock_meter_event.return_value = MagicMock(id="evt_test_123")

            # Report overage for all periods
            total_reported = 0
            for period in periods:
                result = await consumption_service._report_overage_to_stripe(
                    usage_period_id=period.id,
                    subscription_id=subscription_with_overage.id,
                )
                assert result["success"] is True
                total_reported += period.overage_used - period.overage_reported

            # Verify all meter events were created
            assert mock_meter_event.call_count == len(periods)

            # Verify total reported amount
            expected_total = sum(
                overage_used - overage_reported
                for overage_used, overage_reported in periods_data
            )
            assert total_reported == expected_total

    @pytest.mark.asyncio
    async def test_overage_disabled_by_default(self, consumption_service):
        """Test that overage is disabled by default for new subscriptions."""
        # Create subscription without explicitly enabling overage
        subscription = Subscription(
            id=uuid4(),
            organization_id=uuid4(),
            stripe_subscription_id="sub_test_123",
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            # overage_enabled not set (should default to False)
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        consumption_service.db.add(subscription)
        await consumption_service.db.commit()

        # Verify overage is disabled by default
        retrieved_subscription = await consumption_service.db.get(
            Subscription, subscription.id
        )
        assert retrieved_subscription.overage_enabled is False

        # Test that overage consumption fails
        credits_needed = 1200  # Would require overage
        success, reason = await consumption_service.consume_credits(
            organization_id=subscription.organization_id, credits_needed=credits_needed
        )

        assert success is False
        assert "No credits available and overage disabled" in reason
