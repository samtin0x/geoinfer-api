"""Database schema validation tests."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from src.database.models import (
    Subscription,
    SubscriptionStatus,
    CreditGrant,
    GrantType,
    UsagePeriod,
    UsageRecord,
    UsageType,
    OperationType,
    TopUp,
    Organization,
    PlanTier,
)
from src.database.models.alerts import Alert, AlertSettings
from tests.factories import (
    OrganizationFactory,
    SubscriptionFactory,
)


class TestDatabaseSchema:
    """Test suite for database schema validation."""

    @pytest_asyncio.fixture
    async def test_organization(self, db_session):
        """Create a test organization."""
        return await OrganizationFactory.create_async(
            db_session,
            plan_tier=PlanTier.SUBSCRIBED,
            name="Test Organization",
        )

    @pytest.mark.asyncio
    async def test_subscription_model_creation(self, db_session, test_organization):
        """Test subscription model can be created with all fields."""
        subscription = await SubscriptionFactory.create_async(
            db_session,
            organization_id=test_organization.id,
            stripe_subscription_id="sub_test_123",
            stripe_customer_id="cus_test_456",
            stripe_item_base_id="si_base_123",
            stripe_item_overage_id="si_overage_123",
            stripe_price_base_id="price_base_123",
            stripe_price_overage_id="price_overage_123",
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            overage_enabled=True,
            user_extra_cap=500,
            pause_access=False,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        await db_session.commit()

        # Verify subscription was created
        retrieved = db_session.get(Subscription, subscription.id)
        assert retrieved is not None
        assert retrieved.organization_id == test_organization.id
        assert retrieved.stripe_subscription_id == "sub_test_123"
        assert retrieved.status == SubscriptionStatus.ACTIVE
        assert retrieved.monthly_allowance == 1000
        assert retrieved.overage_enabled is True
        assert retrieved.user_extra_cap == 500

    def test_subscription_relationships(self, db_session, test_organization):
        """Test subscription relationships work correctly."""
        # Create subscription
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
        db_session.add(subscription)

        # Create usage period
        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30),
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        db_session.add(usage_period)

        # Create credit grant
        credit_grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            subscription_id=subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Monthly allowance",
            amount=1000,
            remaining_amount=1000,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(credit_grant)

        # Create alert settings
        alert_settings = AlertSettings(
            subscription_id=subscription.id,
            alert_thresholds=[0.8, 0.9],
            alert_destinations=["admin@example.com"],
            alerts_enabled=True,
        )
        db_session.add(alert_settings)

        # Create alert
        alert = Alert(
            organization_id=test_organization.id,
            subscription_id=subscription.id,
            alert_type="usage",
            alert_category="threshold",
            threshold_percentage=0.8,
            alert_message="Usage at 80% threshold reached",
            severity="warning",
            triggered_at=datetime.now(timezone.utc),
        )
        db_session.add(alert)

        await db_session.commit()

        # Verify relationships work
        retrieved_subscription = db_session.get(Subscription, subscription.id)
        assert len(retrieved_subscription.usage_periods) == 1
        assert len(retrieved_subscription.credit_grants) == 1
        assert retrieved_subscription.alert_settings is not None
        assert len(retrieved_subscription.alerts) == 1

        # Verify back-references work
        retrieved_period = db_session.get(UsagePeriod, usage_period.id)
        assert retrieved_period.subscription.id == subscription.id

        retrieved_grant = db_session.get(CreditGrant, credit_grant.id)
        assert retrieved_grant.subscription.id == subscription.id

        retrieved_alert = db_session.get(Alert, alert.id)
        assert retrieved_alert.subscription.id == subscription.id

    def test_credit_grant_model_creation(self, db_session, test_organization):
        """Test credit grant model can be created with all types."""
        # Test subscription grant
        subscription_grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Monthly allowance",
            amount=1000,
            remaining_amount=1000,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(subscription_grant)

        # Test topup grant
        topup_grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            grant_type=GrantType.TOPUP,
            description="Growth Topup",
            amount=700,
            remaining_amount=700,
            expires_at=datetime.now(timezone.utc) + timedelta(days=90),
        )
        db_session.add(topup_grant)

        # Test trial grant
        trial_grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            grant_type=GrantType.TRIAL,
            description="Trial credits",
            amount=100,
            remaining_amount=100,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(trial_grant)

        await db_session.commit()

        # Verify all grants were created
        grants = db_session.query(CreditGrant).all()
        assert len(grants) == 3

        # Verify grant types
        grant_types = {grant.grant_type for grant in grants}
        assert GrantType.SUBSCRIPTION in grant_types
        assert GrantType.TOPUP in grant_types
        assert GrantType.TRIAL in grant_types

    def test_topup_model_creation(self, db_session, test_organization):
        """Test topup model can be created correctly."""
        topup = TopUp(
            id=uuid4(),
            organization_id=test_organization.id,
            stripe_payment_intent_id="pi_test_123",
            description="Growth Topup",
            price_paid=49.0,
            credits_purchased=700,
            package_type=GrantType.TOPUP,
            expires_at=datetime.now(timezone.utc) + timedelta(days=90),
        )
        db_session.add(topup)
        await db_session.commit()

        # Verify topup was created
        retrieved = db_session.get(TopUp, topup.id)
        assert retrieved is not None
        assert retrieved.organization_id == test_organization.id
        assert retrieved.credits_purchased == 700
        assert retrieved.price_paid == 49.0
        assert retrieved.package_type == GrantType.TOPUP

    def test_usage_period_model_creation(self, db_session, test_organization):
        """Test usage period model can be created correctly."""
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
        db_session.add(subscription)
        await db_session.commit()

        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30),
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        db_session.add(usage_period)
        await db_session.commit()

        # Verify usage period was created
        retrieved = db_session.get(UsagePeriod, usage_period.id)
        assert retrieved is not None
        assert retrieved.subscription_id == subscription.id
        assert retrieved.overage_used == 0
        assert retrieved.overage_reported == 0
        assert retrieved.closed is False

    def test_usage_record_model_creation(self, db_session, test_organization):
        """Test usage record model can be created correctly."""
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
        db_session.add(subscription)

        credit_grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            subscription_id=subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Monthly allowance",
            amount=1000,
            remaining_amount=1000,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(credit_grant)
        await db_session.commit()

        usage_record = UsageRecord(
            id=uuid4(),
            organization_id=test_organization.id,
            credits_consumed=100,
            usage_type=UsageType.GEOINFER_GLOBAL_0_0_1,
            subscription_id=subscription.id,
            operation_type=OperationType.CONSUMPTION,
        )
        db_session.add(usage_record)
        await db_session.commit()

        # Verify usage record was created
        retrieved = db_session.get(UsageRecord, usage_record.id)
        assert retrieved is not None
        assert retrieved.organization_id == test_organization.id
        assert retrieved.credits_consumed == 100
        assert retrieved.usage_type == UsageType.GEOINFER_GLOBAL_0_0_1
        assert retrieved.subscription_id == subscription.id
        assert retrieved.operation_type == OperationType.CONSUMPTION

    def test_alert_model_creation(self, db_session, test_organization):
        """Test alert model can be created correctly."""
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
        db_session.add(subscription)
        await db_session.commit()

        alert = Alert(
            id=uuid4(),
            organization_id=test_organization.id,
            subscription_id=subscription.id,
            alert_type="usage",
            alert_category="threshold",
            threshold_percentage=0.8,
            alert_message="Usage at 80% threshold reached",
            severity="warning",
            triggered_at=datetime.now(timezone.utc),
        )
        db_session.add(alert)
        await db_session.commit()

        # Verify alert was created
        retrieved = db_session.get(Alert, alert.id)
        assert retrieved is not None
        assert retrieved.organization_id == test_organization.id
        assert retrieved.subscription_id == subscription.id
        assert retrieved.alert_type == "usage"
        assert retrieved.alert_category == "threshold"
        assert retrieved.threshold_percentage == 0.8
        assert retrieved.severity == "warning"

    def test_alert_settings_model_creation(self, db_session, test_organization):
        """Test alert settings model can be created correctly."""
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
        db_session.add(subscription)
        await db_session.commit()

        alert_settings = AlertSettings(
            id=uuid4(),
            subscription_id=subscription.id,
            alert_thresholds=[0.5, 0.8, 0.9, 0.95],
            alert_destinations=["admin@example.com", "billing@example.com"],
            alerts_enabled=True,
        )
        db_session.add(alert_settings)
        await db_session.commit()

        # Verify alert settings were created
        retrieved = db_session.get(AlertSettings, alert_settings.id)
        assert retrieved is not None
        assert retrieved.subscription_id == subscription.id
        assert retrieved.alert_thresholds == [0.5, 0.8, 0.9, 0.95]
        assert retrieved.alert_destinations == [
            "admin@example.com",
            "billing@example.com",
        ]
        assert retrieved.alerts_enabled is True

    def test_organization_plan_tier_enum(self, db_session):
        """Test organization plan tier enum values."""
        # Test all plan tiers can be created
        for plan_tier in PlanTier:
            org = Organization(
                id=uuid4(),
                name=f"Test Organization {plan_tier.value}",
                plan_tier=plan_tier,
            )
            db_session.add(org)

        await db_session.commit()

        # Verify all plan tiers were created
        organizations = db_session.query(Organization).all()
        assert len(organizations) == len(PlanTier)

        plan_tiers = {org.plan_tier for org in organizations}
        assert PlanTier.FREE in plan_tiers
        assert PlanTier.SUBSCRIBED in plan_tiers
        assert PlanTier.ENTERPRISE in plan_tiers

    def test_subscription_status_enum(self, db_session, test_organization):
        """Test subscription status enum values."""
        # Test all subscription statuses can be created
        for status in SubscriptionStatus:
            subscription = Subscription(
                id=uuid4(),
                organization_id=test_organization.id,
                description=f"Test Subscription {status.value}",
                price_paid=60.0,
                monthly_allowance=1000,
                overage_unit_price=0.06,
                status=status,
                current_period_start=datetime.now(timezone.utc),
                current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
            )
            db_session.add(subscription)

        await db_session.commit()

        # Verify all statuses were created
        subscriptions = db_session.query(Subscription).all()
        assert len(subscriptions) == len(SubscriptionStatus)

        statuses = {sub.status for sub in subscriptions}
        assert SubscriptionStatus.ACTIVE in statuses
        assert SubscriptionStatus.INACTIVE in statuses
        assert SubscriptionStatus.CANCELLED in statuses
        assert SubscriptionStatus.PAST_DUE in statuses

    def test_grant_type_enum(self, db_session, test_organization):
        """Test grant type enum values."""
        # Test all grant types can be created
        for grant_type in GrantType:
            grant = CreditGrant(
                id=uuid4(),
                organization_id=test_organization.id,
                grant_type=grant_type,
                description=f"Test Grant {grant_type.value}",
                amount=100,
                remaining_amount=100,
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
            db_session.add(grant)

        await db_session.commit()

        # Verify all grant types were created
        grants = db_session.query(CreditGrant).all()
        assert len(grants) == len(GrantType)

        grant_types = {grant.grant_type for grant in grants}
        assert GrantType.SUBSCRIPTION in grant_types
        assert GrantType.TOPUP in grant_types
        assert GrantType.TRIAL in grant_types
        assert GrantType.GEOINFER in grant_types

    def test_cascade_deletion_subscription(self, db_session, test_organization):
        """Test cascade deletion when subscription is deleted."""
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
        db_session.add(subscription)

        # Create related records
        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30),
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        db_session.add(usage_period)

        credit_grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            subscription_id=subscription.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Monthly allowance",
            amount=1000,
            remaining_amount=1000,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(credit_grant)

        alert_settings = AlertSettings(
            subscription_id=subscription.id,
            alert_thresholds=[0.8],
            alert_destinations=["admin@example.com"],
            alerts_enabled=True,
        )
        db_session.add(alert_settings)

        alert = Alert(
            organization_id=test_organization.id,
            subscription_id=subscription.id,
            alert_type="usage",
            alert_category="threshold",
            threshold_percentage=0.8,
            alert_message="Usage at 80% threshold reached",
            severity="warning",
            triggered_at=datetime.now(timezone.utc),
        )
        db_session.add(alert)

        await db_session.commit()

        # Verify related records exist
        assert db_session.get(UsagePeriod, usage_period.id) is not None
        assert db_session.get(CreditGrant, credit_grant.id) is not None
        assert db_session.get(AlertSettings, alert_settings.id) is not None
        assert db_session.get(Alert, alert.id) is not None

        # Delete subscription
        db_session.delete(subscription)
        await db_session.commit()

        # Verify related records were cascade deleted
        assert db_session.get(UsagePeriod, usage_period.id) is None
        assert db_session.get(CreditGrant, credit_grant.id) is None
        assert db_session.get(AlertSettings, alert_settings.id) is None
        assert db_session.get(Alert, alert.id) is None

    def test_cascade_deletion_organization(self, db_session):
        """Test cascade deletion when organization is deleted."""
        organization = Organization(
            id=uuid4(),
            name="Test Organization",
            plan_tier=PlanTier.SUBSCRIBED,
        )
        db_session.add(organization)

        subscription = Subscription(
            id=uuid4(),
            organization_id=organization.id,
            description="Test Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(subscription)

        topup = TopUp(
            id=uuid4(),
            organization_id=organization.id,
            description="Test Topup",
            price_paid=49.0,
            credits_purchased=700,
            package_type=GrantType.TOPUP,
            expires_at=datetime.now(timezone.utc) + timedelta(days=90),
        )
        db_session.add(topup)

        credit_grant = CreditGrant(
            id=uuid4(),
            organization_id=organization.id,
            grant_type=GrantType.TRIAL,
            description="Trial credits",
            amount=100,
            remaining_amount=100,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(credit_grant)

        alert = Alert(
            organization_id=organization.id,
            alert_type="system",
            alert_category="test",
            alert_message="Test alert",
            severity="info",
            triggered_at=datetime.now(timezone.utc),
        )
        db_session.add(alert)

        await db_session.commit()

        # Verify records exist
        assert db_session.get(Subscription, subscription.id) is not None
        assert db_session.get(TopUp, topup.id) is not None
        assert db_session.get(CreditGrant, credit_grant.id) is not None
        assert db_session.get(Alert, alert.id) is not None

        # Delete organization
        db_session.delete(organization)
        await db_session.commit()

        # Verify all related records were cascade deleted
        assert db_session.get(Subscription, subscription.id) is None
        assert db_session.get(TopUp, topup.id) is None
        assert db_session.get(CreditGrant, credit_grant.id) is None
        assert db_session.get(Alert, alert.id) is None

    def test_credit_grant_constraints(self, db_session, test_organization):
        """Test credit grant constraints and validations."""
        # Test negative amount should fail (would be caught by database constraints)
        try:
            grant = CreditGrant(
                id=uuid4(),
                organization_id=test_organization.id,
                grant_type=GrantType.SUBSCRIPTION,
                description="Invalid grant",
                amount=-100,  # Negative amount
                remaining_amount=-100,
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
            db_session.add(grant)
            await db_session.commit()
            # If we reach here, the constraint didn't work as expected
            assert False, "Negative amount should not be allowed"
        except Exception:
            # Expected - database constraints should prevent this
            db_session.rollback()

    def test_subscription_unique_constraints(self, db_session, test_organization):
        """Test subscription unique constraints."""
        # Create first subscription
        subscription1 = Subscription(
            id=uuid4(),
            organization_id=test_organization.id,
            stripe_subscription_id="sub_unique_123",
            description="First Subscription",
            price_paid=60.0,
            monthly_allowance=1000,
            overage_unit_price=0.06,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(subscription1)
        await db_session.commit()

        # Try to create duplicate stripe_subscription_id
        try:
            subscription2 = Subscription(
                id=uuid4(),
                organization_id=uuid4(),  # Different organization
                stripe_subscription_id="sub_unique_123",  # Same stripe ID
                description="Duplicate Subscription",
                price_paid=60.0,
                monthly_allowance=1000,
                overage_unit_price=0.06,
                status=SubscriptionStatus.ACTIVE,
                current_period_start=datetime.now(timezone.utc),
                current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
            )
            db_session.add(subscription2)
            await db_session.commit()
            # If we reach here, the unique constraint didn't work
            assert False, "Duplicate stripe_subscription_id should not be allowed"
        except Exception:
            # Expected - unique constraint should prevent this
            db_session.rollback()

    def test_datetime_fields_timezone_aware(self, db_session, test_organization):
        """Test that datetime fields are properly timezone-aware."""
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
        db_session.add(subscription)

        credit_grant = CreditGrant(
            id=uuid4(),
            organization_id=test_organization.id,
            grant_type=GrantType.SUBSCRIPTION,
            description="Monthly allowance",
            amount=1000,
            remaining_amount=1000,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(credit_grant)

        await db_session.commit()

        # Verify datetime fields are timezone-aware
        retrieved_subscription = db_session.get(Subscription, subscription.id)
        assert retrieved_subscription.current_period_start.tzinfo is not None
        assert retrieved_subscription.current_period_end.tzinfo is not None
        assert retrieved_subscription.created_at.tzinfo is not None
        assert retrieved_subscription.updated_at.tzinfo is not None

        retrieved_grant = db_session.get(CreditGrant, credit_grant.id)
        assert retrieved_grant.expires_at.tzinfo is not None
        assert retrieved_grant.created_at.tzinfo is not None
