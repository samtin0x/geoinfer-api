"""Subscription management tests."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from src.database.models import (
    Subscription,
    SubscriptionStatus,
    GrantType,
    Organization,
    PlanTier,
)
from src.database.models.alerts import AlertSettings
from src.modules.billing.constants import (
    SubscriptionPackage,
    SUBSCRIPTION_PACKAGES,
)
from src.modules.billing.application.use_cases import SubscriptionUseCases


class TestSubscriptionManagement:
    """Test suite for subscription management operations."""

    @pytest.fixture
    def use_cases(self, db_session):
        """Create subscription use cases instance."""
        return SubscriptionUseCases(db_session)

    @pytest.fixture
    def test_organization(self, db_session):
        """Create a test organization."""
        org = Organization(
            id=uuid4(),
            name="Test Organization",
            plan_tier=PlanTier.FREE,
        )
        db_session.add(org)
        await db_session.commit()
        return org

    @pytest.fixture
    def active_subscription(self, db_session, test_organization):
        """Create an active subscription."""
        subscription = Subscription(
            id=uuid4(),
            organization_id=test_organization.id,
            stripe_subscription_id="sub_existing_123",
            stripe_customer_id="cus_existing_456",
            description="Existing Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            overage_enabled=False,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(subscription)
        await db_session.commit()
        return subscription

    @pytest.mark.asyncio
    async def test_create_subscription_success(self, use_cases, test_organization):
        """Test successful subscription creation."""
        # Mock Stripe session creation
        with patch("stripe.checkout.Session.create") as mock_session:
            mock_session.return_value = MagicMock(
                id="cs_test_session_123",
                url="https://checkout.stripe.com/test_session_123",
            )

            # Create subscription
            result = await use_cases.create_subscription(
                organization_id=test_organization.id,
                package=SubscriptionPackage.PRO_MONTHLY,
                customer_email="test@example.com",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
            )

            assert result["success"] is True
            assert "checkout_session_id" in result
            assert "checkout_url" in result
            assert result["checkout_session_id"] == "cs_test_session_123"

            # Verify Stripe session was created with correct parameters
            mock_session.assert_called_once()
            call_args = mock_session.call_args[1]

            # Verify subscription package configuration was used
            package_config = SUBSCRIPTION_PACKAGES[SubscriptionPackage.PRO_MONTHLY]
            assert call_args["line_items"][0]["price"] == package_config.base_price_id
            assert call_args["customer_email"] == "test@example.com"
            assert call_args["success_url"] == "https://example.com/success"
            assert call_args["cancel_url"] == "https://example.com/cancel"

    @pytest.mark.asyncio
    async def test_create_subscription_stripe_failure(
        self, use_cases, test_organization
    ):
        """Test subscription creation fails when Stripe fails."""
        with patch("stripe.checkout.Session.create") as mock_session:
            mock_session.side_effect = Exception("Stripe API error")

            result = await use_cases.create_subscription(
                organization_id=test_organization.id,
                package=SubscriptionPackage.PRO_MONTHLY,
                customer_email="test@example.com",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
            )

            assert result["success"] is False
            assert "error" in result
            assert "Stripe API error" in result["error"]

    @pytest.mark.asyncio
    async def test_create_subscription_invalid_package(
        self, use_cases, test_organization
    ):
        """Test subscription creation with invalid package."""
        result = await use_cases.create_subscription(
            organization_id=test_organization.id,
            package="INVALID_PACKAGE",  # Invalid package
            customer_email="test@example.com",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )

        assert result["success"] is False
        assert "error" in result
        assert "Invalid subscription package" in result["error"]

    @pytest.mark.asyncio
    async def test_subscription_webhook_checkout_completed(
        self, use_cases, test_organization
    ):
        """Test subscription creation via webhook when checkout completes."""
        # Mock Stripe subscription creation
        with patch("stripe.Subscription.create") as mock_sub_create:
            mock_subscription = MagicMock()
            mock_subscription.id = "sub_new_123"
            mock_subscription.customer = "cus_new_456"
            mock_subscription.items.data = [
                MagicMock(price=MagicMock(id="price_pro_monthly_eur"))
            ]
            mock_subscription.current_period_start = int(
                datetime.now(timezone.utc).timestamp()
            )
            mock_subscription.current_period_end = int(
                (datetime.now(timezone.utc) + timedelta(days=30)).timestamp()
            )
            mock_sub_create.return_value = mock_subscription

            # Process webhook
            webhook_data = {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_test_123",
                        "customer_details": {"email": "test@example.com"},
                        "metadata": {
                            "organization_id": str(test_organization.id),
                            "package": "PRO_MONTHLY",
                        },
                    }
                },
            }

            result = await use_cases.process_webhook(webhook_data)

            assert result["success"] is True

            # Verify subscription was created in database
            subscriptions = await use_cases.db.execute(
                "SELECT * FROM subscriptions WHERE organization_id = :org_id",
                {"org_id": test_organization.id},
            )
            subscription_records = subscriptions.fetchall()
            assert len(subscription_records) == 1

            sub = subscription_records[0]
            assert sub.stripe_subscription_id == "sub_new_123"
            assert sub.stripe_customer_id == "cus_new_456"
            assert sub.status == SubscriptionStatus.ACTIVE
            assert sub.monthly_allowance == 1000

            # Verify usage period was created
            usage_periods = await use_cases.db.execute(
                "SELECT * FROM usage_periods WHERE subscription_id = :sub_id",
                {"sub_id": sub.id},
            )
            period_records = usage_periods.fetchall()
            assert len(period_records) == 1

            # Verify credit grant was created
            credit_grants = await use_cases.db.execute(
                "SELECT * FROM credit_grants WHERE subscription_id = :sub_id",
                {"sub_id": sub.id},
            )
            grant_records = credit_grants.fetchall()
            assert len(grant_records) == 1

            grant = grant_records[0]
            assert grant.grant_type == GrantType.SUBSCRIPTION
            assert grant.amount == 1000
            assert grant.remaining_amount == 1000

    @pytest.mark.asyncio
    async def test_subscription_upgrade_monthly_to_yearly(
        self, use_cases, active_subscription
    ):
        """Test upgrading from monthly to yearly subscription."""
        # Mock Stripe subscription modification
        with patch("stripe.Subscription.modify") as mock_sub_modify:
            mock_subscription = MagicMock()
            mock_subscription.id = active_subscription.stripe_subscription_id
            mock_sub_modify.return_value = mock_subscription

            result = await use_cases.upgrade_subscription(
                subscription_id=active_subscription.id,
                target_package=SubscriptionPackage.PRO_YEARLY,
            )

            assert result["success"] is True

            # Verify Stripe subscription was modified
            mock_sub_modify.assert_called_once()
            call_args = mock_sub_modify.call_args[1]

            package_config = SUBSCRIPTION_PACKAGES[SubscriptionPackage.PRO_YEARLY]
            assert call_args["items"][0]["price"] == package_config.base_price_id

    @pytest.mark.asyncio
    async def test_subscription_downgrade_yearly_to_monthly(
        self, use_cases, active_subscription
    ):
        """Test downgrading from yearly to monthly subscription."""
        # First, update subscription to yearly package
        active_subscription.stripe_subscription_id = "sub_yearly_123"
        await use_cases.db.commit()

        with patch("stripe.Subscription.modify") as mock_sub_modify:
            mock_subscription = MagicMock()
            mock_subscription.id = "sub_yearly_123"
            mock_sub_modify.return_value = mock_subscription

            result = await use_cases.downgrade_subscription(
                subscription_id=active_subscription.id,
                target_package=SubscriptionPackage.PRO_MONTHLY,
            )

            assert result["success"] is True

            # Verify downgrade was scheduled for end of period
            await use_cases.db.refresh(active_subscription)
            assert (
                active_subscription.status == SubscriptionStatus.ACTIVE
            )  # Still active until period end

    @pytest.mark.asyncio
    async def test_subscription_cancellation_immediate(
        self, use_cases, active_subscription
    ):
        """Test immediate subscription cancellation."""
        with patch("stripe.Subscription.delete") as mock_sub_delete:
            mock_sub_delete.return_value = MagicMock()

            result = await use_cases.cancel_subscription(
                subscription_id=active_subscription.id,
                cancel_at_period_end=False,  # Immediate cancellation
            )

            assert result["success"] is True

            # Verify Stripe subscription was cancelled
            mock_sub_delete.assert_called_once_with(
                active_subscription.stripe_subscription_id
            )

            # Verify database subscription was updated
            await use_cases.db.refresh(active_subscription)
            assert active_subscription.status == SubscriptionStatus.CANCELLED
            assert active_subscription.pause_access is True

    @pytest.mark.asyncio
    async def test_subscription_cancellation_end_of_period(
        self, use_cases, active_subscription
    ):
        """Test subscription cancellation at end of period."""
        with patch("stripe.Subscription.modify") as mock_sub_modify:
            mock_subscription = MagicMock()
            mock_subscription.id = active_subscription.stripe_subscription_id
            mock_sub_modify.return_value = mock_subscription

            result = await use_cases.cancel_subscription(
                subscription_id=active_subscription.id,
                cancel_at_period_end=True,  # Cancel at period end
            )

            assert result["success"] is True

            # Verify Stripe subscription was modified to cancel at period end
            mock_sub_modify.assert_called_once()
            call_args = mock_sub_modify.call_args[1]
            assert call_args["cancel_at_period_end"] is True

            # Verify database subscription status remains active until period end
            await use_cases.db.refresh(active_subscription)
            assert active_subscription.status == SubscriptionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_subscription_reactivation(self, use_cases, active_subscription):
        """Test reactivating a cancelled subscription."""
        # First, cancel the subscription
        active_subscription.status = SubscriptionStatus.CANCELLED
        await use_cases.db.commit()

        with patch("stripe.Subscription.modify") as mock_sub_modify:
            mock_subscription = MagicMock()
            mock_subscription.id = active_subscription.stripe_subscription_id
            mock_sub_modify.return_value = mock_subscription

            result = await use_cases.reactivate_subscription(
                subscription_id=active_subscription.id,
            )

            assert result["success"] is True

            # Verify Stripe subscription was reactivated
            mock_sub_modify.assert_called_once()
            call_args = mock_sub_modify.call_args[1]
            assert call_args["cancel_at_period_end"] is False

            # Verify database subscription was reactivated
            await use_cases.db.refresh(active_subscription)
            assert active_subscription.status == SubscriptionStatus.ACTIVE
            assert active_subscription.pause_access is False

    @pytest.mark.asyncio
    async def test_subscription_status_transitions(
        self, use_cases, active_subscription
    ):
        """Test subscription status transitions."""
        # Test ACTIVE → PAST_DUE transition
        active_subscription.status = SubscriptionStatus.PAST_DUE
        await use_cases.db.commit()

        # Simulate payment failure webhook
        webhook_data = {
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "subscription": active_subscription.stripe_subscription_id,
                }
            },
        }

        result = await use_cases.process_webhook(webhook_data)
        assert result["success"] is True

        # Verify subscription status updated
        await use_cases.db.refresh(active_subscription)
        assert active_subscription.status == SubscriptionStatus.PAST_DUE

    @pytest.mark.asyncio
    async def test_subscription_period_renewal(self, use_cases, active_subscription):
        """Test subscription period renewal process."""
        # Mock successful payment
        with patch("stripe.Invoice.create") as mock_invoice_create:
            mock_invoice = MagicMock()
            mock_invoice.id = "in_test_123"
            mock_invoice.status = "paid"
            mock_invoice_create.return_value = mock_invoice

            # Mock subscription retrieval for new period dates
            with patch("stripe.Subscription.retrieve") as mock_sub_retrieve:
                mock_subscription = MagicMock()
                mock_subscription.current_period_start = int(
                    (datetime.now(timezone.utc) + timedelta(days=30)).timestamp()
                )
                mock_subscription.current_period_end = int(
                    (datetime.now(timezone.utc) + timedelta(days=60)).timestamp()
                )
                mock_sub_retrieve.return_value = mock_subscription

                result = await use_cases.renew_subscription_period(
                    subscription_id=active_subscription.id,
                )

                assert result["success"] is True

                # Verify new usage period was created
                usage_periods = await use_cases.db.execute(
                    "SELECT * FROM usage_periods WHERE subscription_id = :sub_id ORDER BY period_start DESC",
                    {"sub_id": active_subscription.id},
                )
                periods = usage_periods.fetchall()
                assert len(periods) == 2  # Original + new period

                # Verify new credit grant was created
                credit_grants = await use_cases.db.execute(
                    "SELECT * FROM credit_grants WHERE subscription_id = :sub_id ORDER BY created_at DESC",
                    {"sub_id": active_subscription.id},
                )
                grants = credit_grants.fetchall()
                assert len(grants) == 2  # Original + new grant

                # Verify subscription period was updated
                await use_cases.db.refresh(active_subscription)
                assert (
                    active_subscription.current_period_start.date()
                    == (datetime.now(timezone.utc) + timedelta(days=30)).date()
                )

    @pytest.mark.asyncio
    async def test_subscription_overage_enable_disable(
        self, use_cases, active_subscription
    ):
        """Test enabling and disabling overage for a subscription."""
        # Test enabling overage
        result = await use_cases.update_subscription_overage(
            subscription_id=active_subscription.id,
            overage_enabled=True,
            max_overage=500,
        )

        assert result["success"] is True

        # Verify subscription overage settings updated
        await use_cases.db.refresh(active_subscription)
        assert active_subscription.overage_enabled is True
        assert active_subscription.user_extra_cap == 500

        # Test disabling overage
        result = await use_cases.update_subscription_overage(
            subscription_id=active_subscription.id,
            overage_enabled=False,
        )

        assert result["success"] is True

        # Verify overage was disabled
        await use_cases.db.refresh(active_subscription)
        assert active_subscription.overage_enabled is False

    @pytest.mark.asyncio
    async def test_subscription_alert_settings_update(
        self, use_cases, active_subscription
    ):
        """Test updating subscription alert settings."""
        # Create initial alert settings
        alert_settings = AlertSettings(
            subscription_id=active_subscription.id,
            alert_thresholds=[0.8, 0.9],
            alert_destinations=["admin@example.com"],
            alerts_enabled=True,
        )
        use_cases.db.add(alert_settings)
        await use_cases.db.commit()

        # Update alert settings
        result = await use_cases.update_subscription_alerts(
            subscription_id=active_subscription.id,
            alert_thresholds=[0.7, 0.85, 0.95],
            alert_destinations=["admin@example.com", "billing@example.com"],
            alerts_enabled=True,
        )

        assert result["success"] is True

        # Verify settings were updated
        retrieved_settings = await use_cases.db.get(AlertSettings, alert_settings.id)
        assert retrieved_settings.alert_thresholds == [0.7, 0.85, 0.95]
        assert retrieved_settings.alert_destinations == [
            "admin@example.com",
            "billing@example.com",
        ]

    @pytest.mark.asyncio
    async def test_subscription_validation_invalid_organization(self, use_cases):
        """Test subscription operations fail for non-existent organization."""
        fake_org_id = uuid4()

        result = await use_cases.create_subscription(
            organization_id=fake_org_id,
            package=SubscriptionPackage.PRO_MONTHLY,
            customer_email="test@example.com",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )

        assert result["success"] is False
        assert "Organization not found" in result["error"]

    @pytest.mark.asyncio
    async def test_subscription_validation_missing_stripe_customer(
        self, use_cases, test_organization
    ):
        """Test subscription creation fails without Stripe customer."""
        # Remove Stripe customer ID
        test_organization.stripe_customer_id = None
        await use_cases.db.commit()

        result = await use_cases.create_subscription(
            organization_id=test_organization.id,
            package=SubscriptionPackage.PRO_MONTHLY,
            customer_email="test@example.com",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )

        assert result["success"] is False
        assert "Stripe customer not found" in result["error"]
