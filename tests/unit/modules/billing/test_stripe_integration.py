"""Stripe integration and webhook tests."""

import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4
from sqlalchemy import select

from src.database.models import (
    Subscription,
    SubscriptionStatus,
    GrantType,
    UsagePeriod,
    Organization,
    PlanTier,
)
from src.modules.billing.constants import (
    PRICE_PRO_MONTHLY_EUR,
    StripeProductType,
)
from src.modules.billing.stripe.service import StripePaymentService
from tests.unit.modules.billing.fixtures_stripe_webhooks import (
    INVOICE_PAID_EVENT,
    CUSTOMER_SUBSCRIPTION_CREATED_EVENT,
    CHECKOUT_SESSION_COMPLETED_EVENT,
    get_subscription_data_with_items,
)


class TestStripeIntegration:
    """Test suite for Stripe integration and webhook handling."""

    @pytest.fixture
    def stripe_service(self, db_session):
        """Create Stripe service instance."""
        return StripePaymentService(db_session)

    @pytest.fixture
    async def test_organization(self, db_session):
        """Create a test organization with Stripe customer."""
        org = Organization(
            id=uuid4(),
            name="Test Organization",
            plan_tier=PlanTier.FREE,
            stripe_customer_id="cus_test_456",
        )
        db_session.add(org)
        await db_session.commit()
        return org

    @pytest.fixture
    async def active_subscription(self, db_session, test_organization):
        """Create an active subscription."""
        subscription = Subscription(
            id=uuid4(),
            organization_id=test_organization.id,
            stripe_subscription_id="sub_existing_123",
            stripe_customer_id="cus_test_456",
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
    async def test_webhook_signature_validation_success(self, stripe_service):
        """Test successful webhook signature validation."""
        # Mock Stripe webhook construction
        with patch("stripe.Webhook.construct_event") as mock_construct:
            mock_event = MagicMock()
            mock_event.type = "checkout.session.completed"
            mock_event.created = int(datetime.now(timezone.utc).timestamp())
            mock_construct.return_value = mock_event

            payload = json.dumps({"test": "data"}).encode("utf-8")
            signature = "t=1234567890,v1=test_signature"

            result = await stripe_service.validate_webhook_signature(
                payload=payload, signature=signature, webhook_secret="whsec_test_secret"
            )

            assert result is not None
            assert result.type == "checkout.session.completed"

            # Verify Stripe construct_event was called correctly
            mock_construct.assert_called_once_with(
                payload, signature, "whsec_test_secret"
            )

    @pytest.mark.asyncio
    async def test_webhook_signature_validation_invalid_signature(self, stripe_service):
        """Test webhook signature validation with invalid signature."""
        payload = json.dumps({"test": "data"}).encode("utf-8")
        signature = "invalid_signature_format"

        with pytest.raises(Exception):  # Should raise HTTPException or similar
            await stripe_service.validate_webhook_signature(
                payload=payload, signature=signature, webhook_secret="whsec_test_secret"
            )

    @pytest.mark.asyncio
    async def test_webhook_signature_validation_too_old(self, stripe_service):
        """Test webhook signature validation with timestamp too old."""
        with patch("stripe.Webhook.construct_event") as mock_construct:
            mock_event = MagicMock()
            mock_event.type = "checkout.session.completed"
            # Set timestamp to 10 minutes ago (outside 5-minute tolerance)
            mock_event.created = int(
                (datetime.now(timezone.utc) - timedelta(minutes=10)).timestamp()
            )
            mock_construct.return_value = mock_event

            payload = json.dumps({"test": "data"}).encode("utf-8")
            signature = "t=1234567890,v1=test_signature"

            with pytest.raises(Exception):  # Should raise HTTPException or similar
                await stripe_service.validate_webhook_signature(
                    payload=payload,
                    signature=signature,
                    webhook_secret="whsec_test_secret",
                )

    @pytest.mark.asyncio
    async def test_webhook_checkout_session_completed_subscription(
        self, stripe_service, test_organization
    ):
        """Test webhook handling for completed subscription checkout using real Stripe event structure."""
        # Use real Stripe event structure
        webhook_data = CHECKOUT_SESSION_COMPLETED_EVENT.copy()
        webhook_data["data"]["object"]["metadata"]["organization_id"] = str(
            test_organization.id
        )

        result = await stripe_service.process_webhook(webhook_data)

        assert result["success"] is True

        # Verify subscription was created
        subscriptions = await stripe_service.db.execute(
            "SELECT * FROM subscriptions WHERE organization_id = :org_id",
            {"org_id": test_organization.id},
        )
        subscription_records = subscriptions.fetchall()
        assert len(subscription_records) == 1

        sub = subscription_records[0]
        assert sub.stripe_subscription_id == "sub_1SDCfLRrZbaFh87DmGzQpcLQ"
        assert sub.status == SubscriptionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_webhook_checkout_session_completed_topup(
        self, stripe_service, test_organization
    ):
        """Test webhook handling for completed topup checkout."""
        webhook_data = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_topup_123",
                    "metadata": {
                        "organization_id": str(test_organization.id),
                        "package": "GROWTH",
                        "product_type": "topup_package",
                    },
                }
            },
        }

        result = await stripe_service.process_webhook(webhook_data)

        assert result["success"] is True

        # Verify topup was created
        topups = await stripe_service.db.execute(
            "SELECT * FROM topups WHERE organization_id = :org_id",
            {"org_id": test_organization.id},
        )
        topup_records = topups.fetchall()
        assert len(topup_records) == 1

        topup = topup_records[0]
        assert topup.credits_purchased == 700  # GROWTH package
        assert topup.package_type == GrantType.TOPUP

        # Verify credit grant was created
        credit_grants = await stripe_service.db.execute(
            "SELECT * FROM credit_grants WHERE topup_id = :topup_id",
            {"topup_id": topup.id},
        )
        grant_records = credit_grants.fetchall()
        assert len(grant_records) == 1

        grant = grant_records[0]
        assert grant.grant_type == GrantType.TOPUP
        assert grant.amount == 700
        assert grant.remaining_amount == 700

    @pytest.mark.asyncio
    async def test_webhook_invoice_payment_succeeded(
        self, stripe_service, active_subscription
    ):
        """Test webhook handling for successful invoice payment using real Stripe event structure."""
        # Use real Stripe invoice.paid event structure
        webhook_data = INVOICE_PAID_EVENT.copy()
        webhook_data["data"]["object"][
            "subscription"
        ] = active_subscription.stripe_subscription_id

        result = await stripe_service.process_webhook(webhook_data)

        assert result["success"] is True

        # Verify invoice payment was processed
        # The actual behavior depends on your implementation

    @pytest.mark.asyncio
    async def test_webhook_invoice_payment_failed(
        self, stripe_service, active_subscription, test_organization
    ):
        """Test webhook handling for failed invoice payment."""
        # Set organization to SUBSCRIBED
        test_organization.plan_tier = PlanTier.SUBSCRIBED
        await stripe_service.db.commit()

        webhook_data = {
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "subscription": active_subscription.stripe_subscription_id,
                    "attempt_count": 1,
                }
            },
        }

        result = await stripe_service.process_webhook(webhook_data)

        assert result["success"] is True

        # Verify subscription status was updated to past due
        await stripe_service.db.refresh(active_subscription)
        assert active_subscription.status == SubscriptionStatus.PAST_DUE
        assert active_subscription.pause_access is True

        # Verify organization tier is still SUBSCRIBED (not downgraded on first failure)
        await stripe_service.db.refresh(test_organization)
        assert test_organization.plan_tier == PlanTier.SUBSCRIBED

    @pytest.mark.asyncio
    async def test_webhook_customer_subscription_deleted(
        self, stripe_service, active_subscription, test_organization
    ):
        """Test webhook handling for subscription deletion."""
        # Set organization to SUBSCRIBED first
        test_organization.plan_tier = PlanTier.SUBSCRIBED
        await stripe_service.db.commit()

        webhook_data = {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": active_subscription.stripe_subscription_id,
                }
            },
        }

        result = await stripe_service.process_webhook(webhook_data)

        assert result["success"] is True

        # Verify subscription was cancelled in database
        await stripe_service.db.refresh(active_subscription)
        assert active_subscription.status == SubscriptionStatus.CANCELLED

        # Verify organization plan_tier was reverted to FREE
        await stripe_service.db.refresh(test_organization)
        assert test_organization.plan_tier == PlanTier.FREE

    @pytest.mark.asyncio
    async def test_webhook_unknown_event_type(self, stripe_service):
        """Test webhook handling for unknown event types."""
        webhook_data = {
            "type": "unknown.event.type",
            "data": {
                "object": {
                    "id": "test_id",
                }
            },
        }

        result = await stripe_service.process_webhook(webhook_data)

        assert result["success"] is True  # Should not fail, just ignore
        assert result["message"] == "Event type unknown.event.type not handled"

    @pytest.mark.asyncio
    async def test_webhook_processing_idempotency(
        self, stripe_service, test_organization
    ):
        """Test that webhook processing is idempotent."""
        # Process the same webhook twice
        webhook_data = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "metadata": {
                        "organization_id": str(test_organization.id),
                        "package": "PRO_MONTHLY",
                    },
                }
            },
        }

        # First processing
        result1 = await stripe_service.process_webhook(webhook_data)
        assert result1["success"] is True

        # Second processing (should be idempotent)
        result2 = await stripe_service.process_webhook(webhook_data)
        assert result2["success"] is True

        # Verify only one subscription was created
        subscriptions = await stripe_service.db.execute(
            "SELECT * FROM subscriptions WHERE organization_id = :org_id",
            {"org_id": test_organization.id},
        )
        subscription_records = subscriptions.fetchall()
        assert len(subscription_records) == 1

    @pytest.mark.asyncio
    async def test_stripe_service_create_checkout_session(
        self, stripe_service, test_organization
    ):
        """Test creating Stripe checkout session with existing customer ID."""
        with patch("stripe.checkout.Session.create") as mock_session_create:

            # Mock session creation
            mock_session = MagicMock()
            mock_session.id = "cs_test_123"
            mock_session.url = "https://checkout.stripe.com/cs_test_123"
            mock_session_create.return_value = mock_session

            result = await stripe_service.create_checkout_session(
                customer_id="cus_test_456",  # Organization already has customer ID
                price_id=PRICE_PRO_MONTHLY_EUR,
                organization_id=test_organization.id,
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
                product_type=StripeProductType.SUBSCRIPTION,
            )

            assert result.id == "cs_test_123"
            assert result.url == "https://checkout.stripe.com/cs_test_123"

            # Verify Stripe session was created with correct parameters
            mock_session_create.assert_called_once()
            call_args = mock_session_create.call_args[1]

            assert call_args["customer"] == "cus_test_456"  # Uses provided customer ID
            assert call_args["line_items"][0]["price"] == PRICE_PRO_MONTHLY_EUR
            assert call_args["success_url"] == "https://example.com/success"
            assert call_args["cancel_url"] == "https://example.com/cancel"
            assert call_args["mode"] == "subscription"

    @pytest.mark.asyncio
    async def test_stripe_service_overage_reporting(
        self, stripe_service, active_subscription
    ):
        """Test overage usage reporting to Stripe."""
        # Create usage period with overage
        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=active_subscription.id,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30),
            overage_used=250,
            overage_reported=100,  # 150 unreported
            closed=False,
        )
        stripe_service.db.add(usage_period)
        await stripe_service.db.commit()

        # Mock Stripe Billing Meters API
        with patch("stripe.billing.MeterEvent.create") as mock_meter_event:
            mock_meter_event.return_value = MagicMock(id="evt_test_123")

            result = await stripe_service.report_overage_usage(
                usage_period_id=usage_period.id,
            )

            assert result["success"] is True

            # Verify meter event was created with correct payload
            mock_meter_event.assert_called_once()
            call_args = mock_meter_event.call_args[1]

            assert call_args["event_name"] == "credit_overage"
            assert call_args["payload"]["value"] == "150"  # Unreported amount as string
            assert (
                call_args["payload"]["stripe_customer_id"]
                == active_subscription.stripe_customer_id
            )

            # Verify overage_reported was updated
            await stripe_service.db.refresh(usage_period)
            assert usage_period.overage_reported == 250

    @pytest.mark.asyncio
    async def test_stripe_service_webhook_error_handling(self, stripe_service):
        """Test error handling in webhook processing."""
        # Test with malformed webhook data
        malformed_data = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    # Missing required fields
                }
            },
        }

        result = await stripe_service.process_webhook(malformed_data)

        # Should handle gracefully and return error
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_stripe_service_subscription_retrieval(
        self, stripe_service, active_subscription
    ):
        """Test retrieving subscription information from Stripe with correct data structure."""
        with patch("stripe.Subscription.retrieve") as mock_sub_retrieve:
            # Use helper to create subscription data with items (real Stripe structure)
            subscription_data = get_subscription_data_with_items(
                subscription_id=active_subscription.stripe_subscription_id,
                customer_id=active_subscription.stripe_customer_id,
                status="active",
            )

            mock_subscription = MagicMock(**subscription_data)
            mock_sub_retrieve.return_value = mock_subscription

            result = await stripe_service.get_subscription_info(
                subscription_id=active_subscription.stripe_subscription_id
            )

            assert result["success"] is True
            assert result["subscription"]["status"] == "active"

            # Verify Stripe API was called correctly
            mock_sub_retrieve.assert_called_once_with(
                active_subscription.stripe_subscription_id,
                expand=["latest_invoice.payment_intent"],
            )

    @pytest.mark.asyncio
    async def test_subscription_period_extraction_from_items(
        self, stripe_service, test_organization
    ):
        """Test that period fields are correctly extracted from subscription items."""
        # Use real Stripe subscription structure where period is in items
        subscription_data = get_subscription_data_with_items(
            subscription_id="sub_test_period_123",
            customer_id="cus_test_456",
            price_id=PRICE_PRO_MONTHLY_EUR,
            status="active",
        )

        # Create subscription using the service
        from src.modules.billing.constants import SUBSCRIPTION_PACKAGES

        package_info = SUBSCRIPTION_PACKAGES["PRO_MONTHLY"]
        subscription = await stripe_service._find_or_create_subscription(
            organization_id=test_organization.id,
            stripe_subscription_id=subscription_data["id"],
            package_info=package_info,
            subscription_data=subscription_data,
        )

        # Verify period fields were extracted from items
        assert subscription.current_period_start is not None
        assert subscription.current_period_end is not None

        # Verify timestamps match the item's period
        item = subscription_data["items"]["data"][0]
        expected_start = datetime.fromtimestamp(
            item["current_period_start"], timezone.utc
        )
        expected_end = datetime.fromtimestamp(item["current_period_end"], timezone.utc)

        assert subscription.current_period_start == expected_start
        assert subscription.current_period_end == expected_end

    @pytest.mark.asyncio
    async def test_customer_subscription_created_webhook(
        self, stripe_service, test_organization
    ):
        """Test handling customer.subscription.created webhook with real event structure."""
        # Use real Stripe event
        webhook_data = CUSTOMER_SUBSCRIPTION_CREATED_EVENT.copy()

        # Update to use our test organization
        webhook_data["data"]["object"][
            "customer"
        ] = test_organization.stripe_customer_id

        result = await stripe_service.process_webhook(webhook_data)

        assert result["success"] is True

        # Verify subscription was created with correct period from items
        stmt = select(Subscription).where(
            Subscription.stripe_subscription_id == "sub_1SDCfLRrZbaFh87DmGzQpcLQ"
        )
        result = await stripe_service.db.execute(stmt)
        subscription = result.scalar_one_or_none()

        assert subscription is not None
        assert subscription.current_period_start is not None
        assert subscription.current_period_end is not None

        # Verify the periods match the subscription item data
        expected_start = datetime.fromtimestamp(1759273741, timezone.utc)
        expected_end = datetime.fromtimestamp(1761865741, timezone.utc)
        assert subscription.current_period_start == expected_start
        assert subscription.current_period_end == expected_end

        # Verify organization plan_tier was updated to SUBSCRIBED

        await stripe_service.db.refresh(test_organization)
        assert test_organization.plan_tier == PlanTier.SUBSCRIBED

        # Verify credit grant was created
        from src.database.models import CreditGrant

        credit_grant_stmt = select(CreditGrant).where(
            CreditGrant.subscription_id == subscription.id
        )
        credit_grant_result = await stripe_service.db.execute(credit_grant_stmt)
        credit_grant = credit_grant_result.scalar_one_or_none()

        assert credit_grant is not None
        assert credit_grant.grant_type == GrantType.SUBSCRIPTION
        assert credit_grant.amount == subscription.monthly_allowance
        assert credit_grant.remaining_amount == subscription.monthly_allowance
        assert credit_grant.expires_at == subscription.current_period_end

    @pytest.mark.asyncio
    async def test_subscription_updated_to_unpaid_downgrades_organization(
        self, stripe_service, active_subscription, test_organization
    ):
        """Test that subscription updated to unpaid status downgrades organization to FREE."""
        # Set organization to SUBSCRIBED
        test_organization.plan_tier = PlanTier.SUBSCRIBED
        active_subscription.status = SubscriptionStatus.ACTIVE
        await stripe_service.db.commit()

        # Simulate subscription updated to unpaid
        subscription_data = get_subscription_data_with_items(
            subscription_id=active_subscription.stripe_subscription_id,
            customer_id=active_subscription.stripe_customer_id,
            status="unpaid",
        )

        webhook_data = {
            "type": "customer.subscription.updated",
            "data": {"object": subscription_data},
        }

        result = await stripe_service.process_webhook(webhook_data)

        assert result["success"] is True

        # Verify subscription status changed to UNPAID
        await stripe_service.db.refresh(active_subscription)
        assert active_subscription.status == SubscriptionStatus.UNPAID

        # Verify organization downgraded to FREE
        await stripe_service.db.refresh(test_organization)
        assert test_organization.plan_tier == PlanTier.FREE

    @pytest.mark.asyncio
    async def test_invoice_paid_restores_subscription_from_past_due(
        self, stripe_service, active_subscription, test_organization
    ):
        """Test that successful payment restores subscription from PAST_DUE to ACTIVE."""
        # Set subscription to PAST_DUE
        active_subscription.status = SubscriptionStatus.PAST_DUE
        active_subscription.pause_access = True
        test_organization.plan_tier = PlanTier.SUBSCRIBED
        await stripe_service.db.commit()

        webhook_data = {
            "type": "invoice.paid",
            "data": {
                "object": {
                    "subscription": active_subscription.stripe_subscription_id,
                    "status": "paid",
                }
            },
        }

        result = await stripe_service.process_webhook(webhook_data)

        assert result["success"] is True

        # Verify subscription restored
        await stripe_service.db.refresh(active_subscription)
        assert active_subscription.status == SubscriptionStatus.ACTIVE
        assert active_subscription.pause_access is False

        # Verify organization still SUBSCRIBED
        await stripe_service.db.refresh(test_organization)
        assert test_organization.plan_tier == PlanTier.SUBSCRIBED

    @pytest.mark.asyncio
    async def test_subscription_updated_to_canceled_downgrades_organization(
        self, stripe_service, active_subscription, test_organization
    ):
        """Test that subscription cancellation via update event downgrades organization."""
        # Set organization to SUBSCRIBED
        test_organization.plan_tier = PlanTier.SUBSCRIBED
        active_subscription.status = SubscriptionStatus.ACTIVE
        await stripe_service.db.commit()

        # Simulate subscription updated to canceled
        subscription_data = get_subscription_data_with_items(
            subscription_id=active_subscription.stripe_subscription_id,
            customer_id=active_subscription.stripe_customer_id,
            status="canceled",
        )

        webhook_data = {
            "type": "customer.subscription.updated",
            "data": {"object": subscription_data},
        }

        result = await stripe_service.process_webhook(webhook_data)

        assert result["success"] is True

        # Verify subscription status changed to CANCELLED
        await stripe_service.db.refresh(active_subscription)
        assert active_subscription.status == SubscriptionStatus.CANCELLED

        # Verify organization downgraded to FREE
        await stripe_service.db.refresh(test_organization)
        assert test_organization.plan_tier == PlanTier.FREE

    @pytest.mark.asyncio
    async def test_subscription_cancel_at_period_end_keeps_tier_active(
        self, stripe_service, active_subscription, test_organization
    ):
        """Test that cancel_at_period_end keeps organization SUBSCRIBED until period ends."""
        # Set organization to SUBSCRIBED
        test_organization.plan_tier = PlanTier.SUBSCRIBED
        active_subscription.status = SubscriptionStatus.ACTIVE
        await stripe_service.db.commit()

        # Simulate subscription updated with cancel_at_period_end=True but still active
        subscription_data = get_subscription_data_with_items(
            subscription_id=active_subscription.stripe_subscription_id,
            customer_id=active_subscription.stripe_customer_id,
            status="active",  # Still active until period end
        )
        subscription_data["cancel_at_period_end"] = True

        webhook_data = {
            "type": "customer.subscription.updated",
            "data": {"object": subscription_data},
        }

        result = await stripe_service.process_webhook(webhook_data)

        assert result["success"] is True

        # Verify subscription is still ACTIVE
        await stripe_service.db.refresh(active_subscription)
        assert active_subscription.status == SubscriptionStatus.ACTIVE
        assert active_subscription.cancel_at_period_end is True

        # Verify organization stays SUBSCRIBED (benefit until end of period)
        await stripe_service.db.refresh(test_organization)
        assert test_organization.plan_tier == PlanTier.SUBSCRIBED

    @pytest.mark.asyncio
    async def test_subscription_cancel_at_period_end_then_actually_cancels(
        self, stripe_service, active_subscription, test_organization
    ):
        """Test that subscription with cancel_at_period_end eventually downgrades when it cancels."""
        # Set initial state
        test_organization.plan_tier = PlanTier.SUBSCRIBED
        active_subscription.status = SubscriptionStatus.ACTIVE
        active_subscription.cancel_at_period_end = True
        await stripe_service.db.commit()

        # Simulate subscription.deleted event (subscription has now actually cancelled)
        webhook_data = {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": active_subscription.stripe_subscription_id,
                    "cancel_at_period_end": False,  # No longer scheduled, now actually cancelled
                }
            },
        }

        result = await stripe_service.process_webhook(webhook_data)

        assert result["success"] is True

        # Verify subscription is CANCELLED
        await stripe_service.db.refresh(active_subscription)
        assert active_subscription.status == SubscriptionStatus.CANCELLED
        assert active_subscription.cancel_at_period_end is False

        # Verify organization downgraded to FREE
        await stripe_service.db.refresh(test_organization)
        assert test_organization.plan_tier == PlanTier.FREE

    @pytest.mark.asyncio
    async def test_yearly_subscription_monthly_credit_grants(
        self, stripe_service, test_organization
    ):
        """Test that yearly subscriptions with monthly metered usage grant credits monthly."""
        from src.database.models import CreditGrant

        # Create a yearly subscription
        base_time = datetime.now(timezone.utc)
        yearly_end = base_time + timedelta(days=365)

        subscription = Subscription(
            id=uuid4(),
            organization_id=test_organization.id,
            stripe_subscription_id="sub_yearly_123",
            stripe_customer_id=test_organization.stripe_customer_id,
            description="Yearly Subscription",
            price_paid=600.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            overage_enabled=True,
            current_period_start=base_time,
            current_period_end=yearly_end,
        )
        stripe_service.db.add(subscription)
        await stripe_service.db.commit()

        # Simulate first month - subscription.updated with metered item period
        month_1_start = int(base_time.timestamp())
        month_1_end = int((base_time + timedelta(days=30)).timestamp())

        webhook_data_month_1 = {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_yearly_123",
                    "status": "active",
                    "cancel_at_period_end": False,
                    "items": {
                        "data": [
                            {
                                "id": "si_base_123",
                                "current_period_start": int(base_time.timestamp()),
                                "current_period_end": int(yearly_end.timestamp()),
                                "price": {
                                    "id": "price_yearly",
                                    "recurring": {
                                        "interval": "year",
                                        "usage_type": "licensed",
                                    },
                                },
                            },
                            {
                                "id": "si_metered_123",
                                "current_period_start": month_1_start,
                                "current_period_end": month_1_end,
                                "price": {
                                    "id": "price_metered",
                                    "recurring": {
                                        "interval": "month",
                                        "usage_type": "metered",
                                    },
                                },
                            },
                        ]
                    },
                }
            },
        }

        result_1 = await stripe_service.handle_webhook_event(webhook_data_month_1)
        assert result_1 is True

        # Verify first month credit grant was created
        grants_stmt_1 = (
            select(CreditGrant)
            .where(
                CreditGrant.subscription_id == subscription.id,
                CreditGrant.grant_type == GrantType.SUBSCRIPTION,
            )
            .order_by(CreditGrant.created_at)
        )
        grants_result_1 = await stripe_service.db.execute(grants_stmt_1)
        grants_1 = grants_result_1.scalars().all()

        assert len(grants_1) == 1
        assert grants_1[0].amount == 1000
        assert grants_1[0].remaining_amount == 1000

        # Simulate second month - subscription.updated with new metered period
        month_2_start = month_1_end
        month_2_end = int((base_time + timedelta(days=60)).timestamp())

        webhook_data_month_2 = {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_yearly_123",
                    "status": "active",
                    "cancel_at_period_end": False,
                    "items": {
                        "data": [
                            {
                                "id": "si_base_123",
                                "current_period_start": int(base_time.timestamp()),
                                "current_period_end": int(
                                    yearly_end.timestamp()
                                ),  # Still yearly
                                "price": {
                                    "id": "price_yearly",
                                    "recurring": {
                                        "interval": "year",
                                        "usage_type": "licensed",
                                    },
                                },
                            },
                            {
                                "id": "si_metered_123",
                                "current_period_start": month_2_start,
                                "current_period_end": month_2_end,  # New monthly period
                                "price": {
                                    "id": "price_metered",
                                    "recurring": {
                                        "interval": "month",
                                        "usage_type": "metered",
                                    },
                                },
                            },
                        ]
                    },
                }
            },
        }

        result_2 = await stripe_service.handle_webhook_event(webhook_data_month_2)
        assert result_2 is True

        # Verify second month credit grant was created
        grants_stmt_2 = (
            select(CreditGrant)
            .where(
                CreditGrant.subscription_id == subscription.id,
                CreditGrant.grant_type == GrantType.SUBSCRIPTION,
            )
            .order_by(CreditGrant.created_at)
        )
        grants_result_2 = await stripe_service.db.execute(grants_stmt_2)
        grants_2 = grants_result_2.scalars().all()

        assert len(grants_2) == 2
        assert grants_2[1].amount == 1000
        assert grants_2[1].remaining_amount == 1000
        assert grants_2[0].expires_at != grants_2[1].expires_at

        # Verify base subscription period is still yearly (within 1 second tolerance for timestamp conversion)
        await stripe_service.db.refresh(subscription)
        assert abs((subscription.current_period_end - yearly_end).total_seconds()) < 1
