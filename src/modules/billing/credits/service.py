"""Credit consumption service for handling credit consumption logic."""

import asyncio
from datetime import datetime, timezone
from typing import List
from uuid import UUID

from sqlalchemy import select, func, and_, not_


from src.database.models import (
    Subscription,
    SubscriptionStatus,
    CreditGrant,
    GrantType,
    UsagePeriod,
    UsageRecord,
    UsageType,
    OperationType,
)
from src.database.models.alerts import AlertSettings, Alert
from src.core.base import BaseService
from src.modules.billing.constants import (
    should_alert,
)


class CreditConsumptionService(BaseService):
    """Service for handling credit consumption logic."""

    async def consume_credits(
        self,
        organization_id: UUID,
        credits_needed: int,
        user_id: UUID | None = None,
        api_key_id: UUID | None = None,
    ) -> tuple[bool, str]:
        """
        Consume credits following the business logic:
        1. Subscription allowance
        2. Wallet top-ups (earliest expiry first)
        3. Overage (if enabled and cap not reached)

        Returns: (success: bool, reason: str)
        """
        # Get active subscription for organization
        subscription = await self._get_active_subscription(organization_id)
        if not subscription:
            return False, "No active subscription found"

        if subscription.pause_access:
            return False, "Account access paused due to payment issues"

        # Get current usage period and alert settings in parallel for better performance
        usage_period, alert_settings = await self._get_usage_period_and_alert_settings(
            subscription.id
        )
        if not usage_period:
            return False, "No active usage period found"

        organization_alert_percentages = (
            alert_settings.alert_thresholds if alert_settings else []
        )

        # Track consumption details
        remaining_needed = credits_needed

        # 1. Consume from subscription allowance
        subscription_grants = await self._get_available_subscription_grants(
            subscription.id
        )
        for grant in subscription_grants:
            if remaining_needed <= 0:
                break

            available = grant.remaining_amount
            to_consume = min(available, remaining_needed)
            grant.remaining_amount -= to_consume
            remaining_needed -= to_consume

            # Record consumption
            await self._record_credit_consumption(
                organization_id=organization_id,
                credits_consumed=to_consume,
                grant_type="subscription",
                subscription_id=subscription.id,
                grant_id=grant.id,
                user_id=user_id,
                api_key_id=api_key_id,
            )

        # 2. Consume from wallet top-ups (earliest expiry first)
        if remaining_needed > 0:
            wallet_grants = await self._get_available_wallet_grants(organization_id)
            for grant in wallet_grants:
                if remaining_needed <= 0:
                    break

                available = grant.remaining_amount
                to_consume = min(available, remaining_needed)
                grant.remaining_amount -= to_consume
                remaining_needed -= to_consume

                # Record consumption
                await self._record_credit_consumption(
                    organization_id=organization_id,
                    credits_consumed=to_consume,
                    grant_type="topup",
                    topup_id=grant.topup_id,
                    grant_id=grant.id,
                    user_id=user_id,
                    api_key_id=api_key_id,
                )

        # 3. Use overage if enabled and needed
        if remaining_needed > 0:
            if subscription.overage_enabled:
                # Check if we've reached the cap
                effective_cap = self._calculate_effective_cap(subscription)
                if usage_period.overage_used + remaining_needed > effective_cap:
                    return False, f"Overage cap of {effective_cap} credits exceeded"

                # Record overage usage (no usage record created since overage isn't a grant)
                usage_period.overage_used += remaining_needed
            else:
                return False, "No credits available and overage disabled"

        # Calculate usage percentage for potential alerts (before consumption changes the numbers)
        initial_monthly_used = (
            subscription.monthly_allowance
            - await self._get_remaining_subscription_credits(subscription.id)
        )
        initial_usage_percentage = (
            initial_monthly_used / subscription.monthly_allowance
            if subscription.monthly_allowance > 0
            else 0
        )

        # Check for usage alerts before consumption to get baseline
        if organization_alert_percentages:
            await self._check_and_record_alerts(
                subscription, initial_usage_percentage, organization_alert_percentages
            )

        await self.db.commit()
        return True, "Credits consumed successfully"

    async def _get_active_subscription(self, organization_id: UUID):
        """Get the active subscription for an organization."""
        stmt = select(Subscription).where(
            and_(
                Subscription.organization_id == organization_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_current_usage_period(self, subscription_id: UUID):
        """Get the current active usage period."""
        stmt = (
            select(UsagePeriod)
            .where(
                and_(
                    UsagePeriod.subscription_id == subscription_id,
                    not_(UsagePeriod.closed),
                )
            )
            .order_by(UsagePeriod.created_at.desc())
        )
        result = await self.db.execute(stmt)
        period = result.scalar_one_or_none()

        return period

    async def _get_usage_period_and_alert_settings(self, subscription_id: UUID):
        """Get usage period and alert settings in parallel for better performance."""
        from sqlalchemy import select

        # Execute both queries in parallel
        usage_period_stmt = (
            select(UsagePeriod)
            .where(
                and_(
                    UsagePeriod.subscription_id == subscription_id,
                    not_(UsagePeriod.closed),
                )
            )
            .order_by(UsagePeriod.created_at.desc())
        )

        alert_settings_stmt = select(AlertSettings).where(
            AlertSettings.subscription_id == subscription_id
        )

        # Execute both queries concurrently
        usage_result, alert_result = await asyncio.gather(
            self.db.execute(usage_period_stmt), self.db.execute(alert_settings_stmt)
        )

        usage_period = usage_result.scalar_one_or_none()
        alert_settings = alert_result.scalar_one_or_none()

        return usage_period, alert_settings

    async def _get_available_subscription_grants(self, subscription_id: UUID):
        """Get available subscription credit grants."""
        from datetime import datetime, timezone

        stmt = (
            select(CreditGrant)
            .where(
                and_(
                    CreditGrant.subscription_id == subscription_id,
                    CreditGrant.grant_type == GrantType.SUBSCRIPTION,
                    CreditGrant.remaining_amount > 0,
                    CreditGrant.expires_at > datetime.now(timezone.utc),
                )
            )
            .order_by(CreditGrant.expires_at.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def _get_available_wallet_grants(self, organization_id: UUID):
        """Get available wallet credit grants (topups and trial), ordered by earliest expiry."""
        from datetime import datetime, timezone

        stmt = (
            select(CreditGrant)
            .where(
                and_(
                    CreditGrant.organization_id == organization_id,
                    CreditGrant.grant_type.in_([GrantType.TOPUP, GrantType.TRIAL]),
                    CreditGrant.remaining_amount > 0,
                    CreditGrant.expires_at > datetime.now(timezone.utc),
                )
            )
            .order_by(CreditGrant.expires_at.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    def _calculate_effective_cap(self, subscription) -> int:
        """Calculate the effective overage cap for a subscription."""
        # TODO: Get overage config from organization settings
        overage_config = {
            "enabled": False,  # Default: no overage
            "max_amount": 5000,  # Default max overage
            "unit_price": 0.06,
        }

        user_cap = subscription.user_extra_cap

        if not overage_config["enabled"]:
            return 0  # Overage disabled

        if user_cap is None:
            return int(overage_config["max_amount"] or 0)  # Use configured max or 0

        if overage_config["max_amount"] is None:
            return int(user_cap)  # No max limit, use user cap

        return int(min(user_cap, overage_config["max_amount"]))

    async def _record_credit_consumption(
        self,
        organization_id: UUID,
        credits_consumed: int,
        grant_type: str,
        subscription_id: UUID | None = None,
        topup_id: UUID | None = None,
        grant_id: UUID | None = None,
        user_id: UUID | None = None,
        api_key_id: UUID | None = None,
    ) -> None:
        """Record credit consumption in usage records."""
        usage_record = UsageRecord(
            organization_id=organization_id,
            credits_consumed=credits_consumed,
            usage_type=UsageType.GEOINFER_GLOBAL_0_0_1,
            subscription_id=subscription_id,
            topup_id=topup_id,
            operation_type=OperationType.CONSUMPTION,
            user_id=user_id,
            api_key_id=api_key_id,
        )
        self.db.add(usage_record)

    async def _check_and_record_alerts(
        self,
        subscription,
        usage_percentage: float,
        organization_alert_percentages: List[float],
    ):
        """Check for alerts and record them to prevent duplicates."""

        # Get current usage period
        usage_period = await self._get_current_usage_period(subscription.id)
        if not usage_period:
            return

        organization_id = subscription.organization_id

        # Get already sent alerts for this organization
        sent_alerts_stmt = select(Alert).where(Alert.organization_id == organization_id)
        sent_alerts_result = await self.db.execute(sent_alerts_stmt)
        sent_alerts = sent_alerts_result.scalars().all()
        # Get set of exact percentages that have already been alerted (1 alert limit per threshold)
        alerted_percentages = {alert.threshold_percentage for alert in sent_alerts}

        # Check for new alerts that should be triggered
        new_alerts = []
        triggered_percentages = should_alert(
            usage_percentage, organization_alert_percentages
        )

        for percentage in triggered_percentages:
            # Create alert type from percentage (e.g., "80%" for 0.8)
            alert_type = f"{percentage*100:.1f}%"

            # Check if this exact percentage has already been alerted (1 alert limit per threshold)
            if percentage not in alerted_percentages:
                new_alerts.append((alert_type, percentage))

                # Record the alert as triggered
                alert_record = Alert(
                    organization_id=organization_id,
                    subscription_id=subscription.id,
                    alert_type="usage",
                    alert_category="threshold",
                    threshold_percentage=percentage,
                    alert_message=f"Usage at {percentage*100:.1f}% threshold reached",
                    severity="warning",
                    triggered_at=datetime.now(timezone.utc),
                )
                self.db.add(alert_record)

        # Trigger new alerts
        for alert_type, percentage in new_alerts:
            await self._trigger_usage_alert(
                organization_id=subscription.organization_id,
                subscription_id=subscription.id,
                alert_level="usage_alert",
                usage_percentage=usage_percentage,
                subscription_package="unknown",  # TODO: Get actual package info
                alert_message=f"Usage at {percentage*100:.0f}% threshold reached",
            )

    async def _get_remaining_subscription_credits(self, subscription_id: UUID) -> int:
        """Get remaining subscription credits for current period."""
        stmt = select(func.sum(CreditGrant.remaining_amount)).where(
            and_(
                CreditGrant.subscription_id == subscription_id,
                CreditGrant.grant_type == GrantType.SUBSCRIPTION,
                CreditGrant.expires_at > datetime.now(timezone.utc),
            )
        )
        result = await self.db.execute(stmt)
        remaining = result.scalar() or 0
        return int(remaining)

    async def _trigger_usage_alert(
        self,
        organization_id: UUID,
        subscription_id: UUID,
        alert_level: str,
        usage_percentage: float,
        subscription_package: str,
        alert_message: str = None,
    ):
        """Trigger a usage alert (could send email, webhook, etc.)."""
        # This would be implemented to send alerts via email, webhook, etc.
        # For now, just log the alert
        if alert_message:
            self.logger.warning(
                "Usage alert triggered",
                organization_id=str(organization_id),
                subscription_id=str(subscription_id),
                usage_percentage=usage_percentage,
                package=subscription_package,
                message=alert_message,
            )
        else:
            self.logger.warning(
                "Usage alert triggered",
                organization_id=str(organization_id),
                subscription_id=str(subscription_id),
                usage_percentage=usage_percentage,
                package=subscription_package,
                alert_level=alert_level,
            )

        # TODO: Get alert email addresses from organization settings
        self.logger.info(
            "Alert triggered, email notifications not yet implemented",
            organization_id=str(organization_id),
        )
