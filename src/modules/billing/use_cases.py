"""Billing service with subscription, alert, and usage management."""

from datetime import datetime, timezone
from uuid import UUID
from fastapi import status

from sqlalchemy import select, func, and_, not_

from src.database.models import (
    Subscription,
    TopUp,
    UsagePeriod,
    Alert,
    AlertSettings,
)
from src.core.base import BaseService
from src.modules.billing.constants import should_alert
from src.modules.billing.credits import CreditConsumptionService
from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode


class BillingQueryService(BaseService):
    """Read service for billing products (subscriptions and credit packages)."""

    async def fetch_subscriptions(
        self, organization_id: UUID, limit: int, offset: int
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
        self, organization_id: UUID, limit: int, offset: int
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

    async def get_subscription(
        self, subscription_id: UUID, organization_id: UUID
    ) -> Subscription:
        stmt = select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.organization_id == organization_id,
        )

        result = await self.db.execute(stmt)
        subscription = result.scalar_one_or_none()

        if not subscription:
            raise GeoInferException(
                MessageCode.SUBSCRIPTION_NOT_FOUND,
                status.HTTP_404_NOT_FOUND,
            )

        return subscription

    async def get_alert_settings(
        self,
        subscription_id: UUID,
        default_thresholds: list[float] | None = None,
        default_destinations: list[str] | None = None,
        default_locale: str = "en",
    ) -> AlertSettings:
        """Get or create alert settings for a subscription (upsert pattern).

        Args:
            subscription_id: The subscription ID
            default_thresholds: Thresholds to use when creating (defaults to [])
            default_destinations: Email destinations to use when creating (defaults to [])
            default_locale: Locale to use when creating (defaults to "en")

        Returns:
            AlertSettings (always returns, creates if missing)
        """
        stmt = select(AlertSettings).where(
            AlertSettings.subscription_id == subscription_id
        )
        result = await self.db.execute(stmt)
        alert_settings = result.scalar_one_or_none()

        if not alert_settings:
            alert_settings = AlertSettings(
                subscription_id=subscription_id,
                alert_thresholds=(
                    default_thresholds if default_thresholds is not None else []
                ),
                alert_destinations=(
                    default_destinations if default_destinations is not None else []
                ),
                alerts_enabled=False,
                locale=default_locale,
            )
            self.db.add(alert_settings)
            await self.db.commit()
            await self.db.refresh(alert_settings)

        return alert_settings

    async def update_overage_settings(
        self,
        subscription_id: UUID,
        organization_id: UUID,
        enabled: bool,
        user_extra_cap: int | None = None,
    ) -> Subscription:
        subscription = await self.get_subscription(subscription_id, organization_id)

        subscription.overage_enabled = enabled
        # Set user_extra_cap: 0 = no overage, positive number = cap, None = unlimited
        if user_extra_cap is not None:
            subscription.user_extra_cap = user_extra_cap
        elif not enabled:
            # If disabling overage, set cap to 0
            subscription.user_extra_cap = 0

        await self.db.commit()
        await self.db.refresh(subscription)

        return subscription

    async def update_alert_settings(
        self,
        subscription_id: UUID,
        alert_thresholds: list[float] | None = None,
        alert_destinations: list[str] | None = None,
        alerts_enabled: bool | None = None,
        locale: str | None = None,
    ) -> AlertSettings:
        """Update or create alert settings for a subscription (upsert pattern)."""
        # Get or create with provided defaults
        alert_settings = await self.get_alert_settings(
            subscription_id,
            default_thresholds=alert_thresholds,
            default_destinations=alert_destinations,
            default_locale=locale or "en",
        )

        # Update fields if provided
        if alert_thresholds is not None:
            alert_settings.alert_thresholds = alert_thresholds
        if alert_destinations is not None:
            alert_settings.alert_destinations = alert_destinations
        if alerts_enabled is not None:
            alert_settings.alerts_enabled = alerts_enabled
        if locale is not None:
            alert_settings.locale = locale

        if alert_settings.alerts_enabled:
            if (
                not alert_settings.alert_thresholds
                or len(alert_settings.alert_thresholds) == 0
            ):
                raise GeoInferException(
                    MessageCode.ALERT_SETTINGS_NOT_CONFIGURED,
                    status.HTTP_400_BAD_REQUEST,
                    details={
                        "field": "alert_thresholds",
                        "reason": "At least one alert threshold is required when alerts are enabled",
                    },
                )

            if (
                not alert_settings.alert_destinations
                or len(alert_settings.alert_destinations) == 0
            ):
                raise GeoInferException(
                    MessageCode.NO_ALERT_DESTINATIONS,
                    status.HTTP_400_BAD_REQUEST,
                    details={
                        "field": "alert_destinations",
                        "reason": "At least one email destination is required when alerts are enabled",
                    },
                )

        await self.db.commit()
        await self.db.refresh(alert_settings)

        return alert_settings

    async def check_usage_alerts(
        self, organization_id: UUID, limit: int = 50, offset: int = 0
    ) -> tuple[list, int]:
        stmt = select(Subscription).where(
            and_(
                Subscription.organization_id == organization_id,
                Subscription.status == "active",
            )
        )
        result = await self.db.execute(stmt)
        subscriptions = result.scalars().all()

        alerts = []

        for subscription in subscriptions:
            usage_stmt = (
                select(UsagePeriod)
                .where(
                    and_(
                        UsagePeriod.subscription_id == subscription.id,
                        not_(UsagePeriod.closed),
                    )
                )
                .order_by(UsagePeriod.created_at.desc())
            )
            usage_result = await self.db.execute(usage_stmt)
            usage_period = usage_result.scalar_one_or_none()

            if not usage_period:
                continue

            credit_service = CreditConsumptionService(self.db)
            remaining_credits = (
                await credit_service._get_remaining_subscription_credits(
                    UUID(str(subscription.id))
                )
            )
            monthly_used = subscription.monthly_allowance - remaining_credits
            usage_percentage = (
                monthly_used / subscription.monthly_allowance
                if subscription.monthly_allowance > 0
                else 0
            )

            alert_settings = subscription.alert_settings
            alert_percentages = (
                alert_settings.alert_thresholds if alert_settings else []
            )
            alert_destinations = (
                alert_settings.alert_destinations if alert_settings else []
            )

            sent_alerts_stmt = select(Alert).where(
                Alert.organization_id == subscription.organization_id
            )
            sent_alerts_result = await self.db.execute(sent_alerts_stmt)
            sent_alerts = sent_alerts_result.scalars().all()
            alerted_percentages = {alert.threshold_percentage for alert in sent_alerts}

            new_alerts = []
            triggered_percentages = should_alert(usage_percentage, alert_percentages)

            for percentage in triggered_percentages:
                alert_type = f"{percentage*100:.1f}%"

                if percentage not in alerted_percentages:
                    new_alerts.append((alert_type, percentage))

                    alert_record = Alert(
                        organization_id=subscription.organization_id,
                        subscription_id=subscription.id,
                        alert_type="usage",
                        alert_category="threshold",
                        threshold_percentage=percentage,
                        alert_message=f"Usage at {percentage*100:.1f}% threshold reached",
                        severity="warning",
                        triggered_at=datetime.now(timezone.utc),
                    )
                    self.db.add(alert_record)

            for alert_type, percentage in new_alerts:
                alerts.append(
                    {
                        "subscription_id": str(subscription.id),
                        "subscription_name": subscription.description,
                        "usage_percentage": usage_percentage,
                        "alert_message": f"Usage at {percentage*100:.0f}% threshold reached",
                        "alert_type": alert_type,
                        "monthly_allowance": subscription.monthly_allowance,
                        "current_usage": monthly_used,
                        "new_alert": True,
                        "alert_destinations": alert_destinations,
                    }
                )

        await self.db.commit()

        # Get total count before pagination
        total = len(alerts)

        # Apply pagination
        paginated_alerts = alerts[offset : offset + limit]

        return paginated_alerts, total

    async def send_test_alert(
        self, subscription_id: UUID, organization_id: UUID, locale: str = "en"
    ) -> bool:
        subscription = await self.get_subscription(subscription_id, organization_id)

        alert_settings = await self.get_alert_settings(subscription_id)

        if not alert_settings or not alert_settings.alert_destinations:
            raise GeoInferException(
                MessageCode.NO_ALERT_DESTINATIONS,
                status.HTTP_400_BAD_REQUEST,
            )

        test_alert = Alert(
            organization_id=subscription.organization_id,
            subscription_id=subscription.id,
            alert_type="test",
            alert_category="system",
            alert_message=f"Test alert email for subscription: {subscription.description}",
            severity="info",
            locale=locale or alert_settings.locale,
            triggered_at=datetime.now(timezone.utc),
        )
        self.db.add(test_alert)
        await self.db.commit()

        # TODO: Send actual email here
        test_alert.sent_at = datetime.now(timezone.utc)
        await self.db.commit()

        return True
