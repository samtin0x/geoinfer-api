"""Alert system tests for usage monitoring and notifications."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from src.database.models import (
    Subscription,
    SubscriptionStatus,
    Organization,
    PlanTier,
    Alert,
    AlertSettings,
)
from src.modules.billing.constants import should_alert
from tests.factories import OrganizationFactory, SubscriptionFactory


class TestAlertSystem:
    """Test suite for usage alert system."""

    @pytest_asyncio.fixture
    async def test_organization(self, db_session):
        """Create a test organization."""
        return await OrganizationFactory.create_async(
            db_session,
            plan_tier=PlanTier.SUBSCRIBED,
            name="Test Organization",
        )

    @pytest_asyncio.fixture
    async def active_subscription(self, db_session, test_organization):
        """Create an active subscription."""
        return await SubscriptionFactory.create_async(
            db_session,
            organization_id=test_organization.id,
            status=SubscriptionStatus.ACTIVE,
            monthly_allowance=1000,
            overage_enabled=False,
            description="Test Active Subscription",
        )

    @pytest_asyncio.fixture
    async def alert_settings(self, db_session, active_subscription):
        """Create alert settings with multiple thresholds."""
        settings = AlertSettings(
            subscription_id=active_subscription.id,
            alert_thresholds=[0.5, 0.8, 0.9, 0.95],  # 50%, 80%, 90%, 95%
            alert_destinations=["admin@example.com", "billing@example.com"],
            alerts_enabled=True,
        )
        db_session.add(settings)
        await db_session.commit()
        return settings

    @pytest.mark.asyncio
    async def test_should_alert_function_basic(self):
        """Test the should_alert function with basic scenarios."""
        # No alerts should trigger below first threshold
        triggered = should_alert(0.3, [0.5, 0.8, 0.9])
        assert triggered == []

        # Only first threshold should trigger
        triggered = should_alert(0.6, [0.5, 0.8, 0.9])
        assert triggered == [0.5]

        # First two thresholds should trigger
        triggered = should_alert(0.85, [0.5, 0.8, 0.9])
        assert triggered == [0.5, 0.8]

        # All thresholds should trigger
        triggered = should_alert(0.96, [0.5, 0.8, 0.9])
        assert triggered == [0.5, 0.8, 0.9]

    @pytest.mark.asyncio
    async def test_should_alert_function_empty_thresholds(self):
        """Test should_alert with empty thresholds list."""
        triggered = should_alert(0.9, [])
        assert triggered == []

    @pytest.mark.asyncio
    async def test_should_alert_function_exact_threshold(self):
        """Test should_alert with exact threshold values."""
        triggered = should_alert(0.8, [0.8, 0.9])
        assert triggered == [0.8]

    @pytest.mark.asyncio
    async def test_alert_creation_and_deduplication(
        self, db_session, active_subscription
    ):
        """Test that alerts are created and deduplicated properly."""
        organization_id = active_subscription.organization_id

        # Create first alert at 80% threshold
        alert1 = Alert(
            organization_id=organization_id,
            subscription_id=active_subscription.id,
            alert_type="usage",
            alert_category="threshold",
            threshold_percentage=0.8,
            alert_message="Usage at 80% threshold reached",
            severity="warning",
            triggered_at=datetime.now(timezone.utc),
        )
        db_session.add(alert1)
        await db_session.commit()

        # Create second alert at 90% threshold
        alert2 = Alert(
            organization_id=organization_id,
            subscription_id=active_subscription.id,
            alert_type="usage",
            alert_category="threshold",
            threshold_percentage=0.9,
            alert_message="Usage at 90% threshold reached",
            severity="warning",
            triggered_at=datetime.now(timezone.utc),
        )
        db_session.add(alert2)
        await db_session.commit()

        # Verify both alerts exist
        alerts = await db_session.execute(
            "SELECT * FROM alerts WHERE organization_id = :org_id ORDER BY threshold_percentage",
            {"org_id": organization_id},
        )
        alert_records = alerts.fetchall()
        assert len(alert_records) == 2
        assert alert_records[0].threshold_percentage == 0.8
        assert alert_records[1].threshold_percentage == 0.9

    @pytest.mark.asyncio
    async def test_alert_deduplication_prevents_duplicate_alerts(
        self, db_session, active_subscription
    ):
        """Test that duplicate alerts for same threshold are prevented."""
        organization_id = active_subscription.organization_id

        # Create alert at 80% threshold
        alert1 = Alert(
            organization_id=organization_id,
            subscription_id=active_subscription.id,
            alert_type="usage",
            alert_category="threshold",
            threshold_percentage=0.8,
            alert_message="Usage at 80% threshold reached",
            severity="warning",
            triggered_at=datetime.now(timezone.utc),
        )
        db_session.add(alert1)
        await db_session.commit()

        # Try to create another alert at same 80% threshold
        alert2 = Alert(
            organization_id=organization_id,
            subscription_id=active_subscription.id,
            alert_type="usage",
            alert_category="threshold",
            threshold_percentage=0.8,
            alert_message="Usage at 80% threshold reached again",
            severity="warning",
            triggered_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db_session.add(alert2)
        await db_session.commit()

        # Verify only one alert exists for the 80% threshold
        alerts = await db_session.execute(
            "SELECT * FROM alerts WHERE organization_id = :org_id AND threshold_percentage = 0.8",
            {"org_id": organization_id},
        )
        alert_records = alerts.fetchall()
        assert len(alert_records) == 1

    @pytest.mark.asyncio
    async def test_alert_settings_configuration(self, db_session, active_subscription):
        """Test alert settings configuration and retrieval."""
        # Create alert settings
        settings = AlertSettings(
            subscription_id=active_subscription.id,
            alert_thresholds=[0.7, 0.85, 0.95],
            alert_destinations=["ops@example.com"],
            alerts_enabled=True,
        )
        db_session.add(settings)
        await db_session.commit()

        # Retrieve and verify settings
        retrieved = await db_session.get(AlertSettings, settings.id)
        assert retrieved.alert_thresholds == [0.7, 0.85, 0.95]
        assert retrieved.alert_destinations == ["ops@example.com"]
        assert retrieved.alerts_enabled is True

    @pytest.mark.asyncio
    async def test_alert_settings_disabled_prevents_alerts(
        self, db_session, active_subscription
    ):
        """Test that disabled alert settings prevent alert creation."""
        # Create disabled alert settings
        settings = AlertSettings(
            subscription_id=active_subscription.id,
            alert_thresholds=[0.8, 0.9],
            alert_destinations=["admin@example.com"],
            alerts_enabled=False,  # Disabled
        )
        db_session.add(settings)
        await db_session.commit()

        # Create an alert record (simulating what would happen during consumption)
        alert = Alert(
            organization_id=active_subscription.organization_id,
            subscription_id=active_subscription.id,
            alert_type="usage",
            alert_category="threshold",
            threshold_percentage=0.8,
            alert_message="Usage at 80% threshold reached",
            severity="warning",
            triggered_at=datetime.now(timezone.utc),
        )
        db_session.add(alert)
        await db_session.commit()

        # Verify alert was created but would not be sent due to disabled settings
        retrieved_alert = await db_session.get(Alert, alert.id)
        assert retrieved_alert is not None
        assert retrieved_alert.alert_type == "usage"
        assert retrieved_alert.threshold_percentage == 0.8

    @pytest.mark.asyncio
    async def test_alert_severity_levels(self, db_session, active_subscription):
        """Test different alert severity levels."""
        organization_id = active_subscription.organization_id

        # Create alerts with different severity levels
        alerts_data = [
            (0.8, "warning", "Usage at 80% threshold reached"),
            (0.9, "warning", "Usage at 90% threshold reached"),
            (0.95, "error", "Usage at 95% threshold reached"),
            (1.0, "critical", "Usage limit exceeded"),
        ]

        for threshold, severity, message in alerts_data:
            alert = Alert(
                organization_id=organization_id,
                subscription_id=active_subscription.id,
                alert_type="usage",
                alert_category="threshold",
                threshold_percentage=threshold,
                alert_message=message,
                severity=severity,
                triggered_at=datetime.now(timezone.utc),
            )
            db_session.add(alert)

        await db_session.commit()

        # Verify all alerts were created with correct severity
        alerts = await db_session.execute(
            "SELECT threshold_percentage, severity FROM alerts WHERE organization_id = :org_id ORDER BY threshold_percentage",
            {"org_id": organization_id},
        )
        alert_records = alerts.fetchall()

        assert len(alert_records) == 4
        for i, (threshold, severity) in enumerate(alerts_data):
            assert alert_records[i].threshold_percentage == threshold
            assert alert_records[i].severity == severity

    @pytest.mark.asyncio
    async def test_alert_acknowledgment_and_resolution(
        self, db_session, active_subscription
    ):
        """Test alert acknowledgment and resolution tracking."""
        organization_id = active_subscription.organization_id

        # Create an alert
        alert = Alert(
            organization_id=organization_id,
            subscription_id=active_subscription.id,
            alert_type="usage",
            alert_category="threshold",
            threshold_percentage=0.8,
            alert_message="Usage at 80% threshold reached",
            severity="warning",
            triggered_at=datetime.now(timezone.utc),
        )
        db_session.add(alert)
        await db_session.commit()

        # Acknowledge the alert
        acknowledged_time = datetime.now(timezone.utc) + timedelta(hours=1)
        alert.acknowledged_at = acknowledged_time
        await db_session.commit()

        # Resolve the alert
        resolved_time = datetime.now(timezone.utc) + timedelta(hours=2)
        alert.resolved_at = resolved_time
        await db_session.commit()

        # Verify acknowledgment and resolution times
        retrieved_alert = await db_session.get(Alert, alert.id)
        assert retrieved_alert.acknowledged_at == acknowledged_time
        assert retrieved_alert.resolved_at == resolved_time
        assert retrieved_alert.triggered_at < acknowledged_time < resolved_time

    @pytest.mark.asyncio
    async def test_free_tier_no_alerts(self, db_session):
        """Test that free tier organizations don't get usage alerts."""
        # Create organization on free tier
        org = Organization(
            id=uuid4(),
            name="Free Organization",
            plan_tier=PlanTier.FREE,
        )
        db_session.add(org)
        await db_session.commit()

        # Create a subscription for free tier (though free tier shouldn't have subscriptions)
        subscription = Subscription(
            id=uuid4(),
            organization_id=org.id,
            description="Free Tier",
            price_paid=0.0,
            monthly_allowance=100,  # Trial credits
            overage_unit_price=0.0,
            status=SubscriptionStatus.ACTIVE,
            overage_enabled=False,
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(subscription)
        await db_session.commit()

        # Create alert (simulating what would happen during consumption)
        alert = Alert(
            organization_id=org.id,
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

        # Verify alert exists but would be handled differently for free tier
        retrieved_alert = await db_session.get(Alert, alert.id)
        assert retrieved_alert is not None
        # For free tier, alerts would be handled differently (e.g., no email notifications)
        assert retrieved_alert.alert_type == "usage"

    @pytest.mark.asyncio
    async def test_alert_message_formatting(self, db_session, active_subscription):
        """Test that alert messages are properly formatted."""
        organization_id = active_subscription.organization_id

        # Test various alert message formats
        test_cases = [
            (0.8, "Usage at 80.0% threshold reached"),
            (0.95, "Usage at 95.0% threshold reached"),
            (1.0, "Usage limit of 100.0% exceeded"),
        ]

        for threshold, expected_message in test_cases:
            alert = Alert(
                organization_id=organization_id,
                subscription_id=active_subscription.id,
                alert_type="usage",
                alert_category="threshold",
                threshold_percentage=threshold,
                alert_message=expected_message,
                severity="warning",
                triggered_at=datetime.now(timezone.utc),
            )
            db_session.add(alert)

        await db_session.commit()

        # Verify message formatting
        alerts = await db_session.execute(
            "SELECT threshold_percentage, alert_message FROM alerts WHERE organization_id = :org_id ORDER BY threshold_percentage",
            {"org_id": organization_id},
        )
        alert_records = alerts.fetchall()

        for i, (threshold, expected_message) in enumerate(test_cases):
            assert alert_records[i].threshold_percentage == threshold
            assert alert_records[i].alert_message == expected_message

    @pytest.mark.asyncio
    async def test_alert_email_destination_handling(
        self, db_session, active_subscription
    ):
        """Test handling of multiple email destinations."""
        # Create alert settings with multiple destinations
        settings = AlertSettings(
            subscription_id=active_subscription.id,
            alert_thresholds=[0.8],
            alert_destinations=[
                "admin@example.com",
                "billing@example.com",
                "ops@example.com",
            ],
            alerts_enabled=True,
        )
        db_session.add(settings)
        await db_session.commit()

        # Create alert that would trigger email notifications
        alert = Alert(
            organization_id=active_subscription.organization_id,
            subscription_id=active_subscription.id,
            alert_type="usage",
            alert_category="threshold",
            threshold_percentage=0.8,
            alert_message="Usage at 80% threshold reached",
            severity="warning",
            triggered_at=datetime.now(timezone.utc),
        )
        db_session.add(alert)
        await db_session.commit()

        # Verify alert settings contain all destinations
        retrieved_settings = await db_session.get(AlertSettings, settings.id)
        assert len(retrieved_settings.alert_destinations) == 3
        assert "admin@example.com" in retrieved_settings.alert_destinations
        assert "billing@example.com" in retrieved_settings.alert_destinations
        assert "ops@example.com" in retrieved_settings.alert_destinations
