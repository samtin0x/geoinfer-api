"""Credit consumption service for handling credit consumption logic."""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import List
from uuid import UUID

from sqlalchemy import select, func, and_, not_, or_

from src.api.core.constants import (
    FREE_TRIAL_SIGNUP_CREDIT_AMOUNT,
    TRIAL_CREDIT_EXPIRY_DAYS,
)
from src.api.credits.schemas import (
    CreditsSummaryModel,
    SubscriptionCreditsSummaryModel,
    OverageSummaryModel,
    TopupCreditSummaryModel,
    CreditsSummaryTotalsModel,
)
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
        1. Subscription allowance (if subscription exists)
        2. Wallet top-ups (earliest expiry first) - works without subscription
        3. Overage (if enabled and cap not reached, requires subscription)

        Returns: (success: bool, reason: str)
        """
        # Get active subscription for organization (optional - wallet credits can work without it)
        subscription = await self._get_active_subscription(organization_id)

        # Check if subscription is paused
        if subscription and subscription.pause_access:
            return False, "Account access paused due to payment issues"

        # Initialize variables for subscription-specific features
        usage_period = None
        alert_settings = None
        organization_alert_percentages = []

        # Get usage period and alert settings if subscription exists
        if subscription:
            usage_period, alert_settings = (
                await self._get_usage_period_and_alert_settings(subscription.id)
            )
            if not usage_period:
                return False, "No active usage period found"

            organization_alert_percentages = (
                alert_settings.alert_thresholds if alert_settings else []
            )

        # Pre-flight check: Ensure we can fulfill the request before consuming anything
        # Calculate available credits from all sources
        subscription_grants = []
        wallet_grants = []
        available_subscription = 0
        available_wallet = 0

        if subscription:
            subscription_grants = await self._get_available_subscription_grants(
                subscription.id
            )
            available_subscription = sum(
                g.remaining_amount for g in subscription_grants
            )

        wallet_grants = await self._get_available_wallet_grants(organization_id)
        available_wallet = sum(g.remaining_amount for g in wallet_grants)

        total_available = available_subscription + available_wallet
        overage_needed = max(0, credits_needed - total_available)

        # Check if overage would be needed and if it's available
        if overage_needed > 0:
            if not subscription or not subscription.overage_enabled:
                return False, "No credits available"

            effective_cap = self._calculate_effective_cap(subscription)
            if (
                effective_cap != float("inf")
                and usage_period.overage_used + overage_needed > effective_cap
            ):
                return (
                    False,
                    f"Overage cap of {int(effective_cap)} credits exceeded",
                )

        # Track consumption details
        remaining_needed = credits_needed

        # 1. Consume from subscription allowance (if subscription exists)
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

        # 2. Consume from wallet top-ups (earliest expiry first) - works without subscription
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

        # 3. Use overage if enabled and needed (requires subscription)
        if remaining_needed > 0:
            # We already validated overage is available in pre-flight check
            usage_period.overage_used += remaining_needed
            remaining_needed = 0

        # Calculate usage percentage for potential alerts (only if subscription exists)
        if subscription and organization_alert_percentages:
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
            await self._check_and_record_alerts(
                subscription, initial_usage_percentage, organization_alert_percentages
            )

        await self.db.commit()
        return True, "Credits consumed successfully"

    async def _get_active_subscription(self, organization_id: UUID):
        """Get the active subscription for an organization (most recent if multiple exist)."""
        stmt = (
            select(Subscription)
            .where(
                and_(
                    Subscription.organization_id == organization_id,
                    Subscription.status == SubscriptionStatus.ACTIVE,
                )
            )
            .order_by(Subscription.created_at.desc())
            .limit(1)
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
            .limit(1)
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
            .limit(1)
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

    def _calculate_effective_cap(self, subscription: Subscription) -> int | float:
        """Calculate the effective overage cap for a subscription."""
        if not subscription.overage_enabled:
            return 0

        if subscription.user_extra_cap is None:
            return float("inf")  # Unlimited overage

        return int(subscription.user_extra_cap)

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

    async def grant_trial_credits_to_user(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Grant trial credits to a new user."""
        trial_topup_stmt = select(TopUp).where(
            TopUp.organization_id == organization_id,
            TopUp.stripe_payment_intent_id.is_(None),
        )
        trial_topup_result = await self.db.execute(trial_topup_stmt)
        trial_topups = trial_topup_result.scalars().all()

        for topup in trial_topups:
            if topup.package_type == GrantType.TRIAL:
                self.logger.info(f"User {user_id} already has trial credits")
                return True

        trial_expiry = datetime.now(timezone.utc) + timedelta(
            days=TRIAL_CREDIT_EXPIRY_DAYS
        )

        trial_topup = TopUp(
            organization_id=organization_id,
            credits_purchased=FREE_TRIAL_SIGNUP_CREDIT_AMOUNT,
            description="Geoinfer Trial Credits",
            stripe_payment_intent_id=None,
            price_paid=0.0,
            package_type=GrantType.TRIAL,
            expires_at=trial_expiry,
        )

        self.db.add(trial_topup)
        await self.db.flush()

        credit_grant = CreditGrant(
            organization_id=organization_id,
            topup_id=trial_topup.id,
            grant_type=GrantType.TRIAL,
            description="Geoinfer Trial Credits",
            amount=FREE_TRIAL_SIGNUP_CREDIT_AMOUNT,
            remaining_amount=FREE_TRIAL_SIGNUP_CREDIT_AMOUNT,
            expires_at=trial_expiry,
        )

        self.db.add(credit_grant)
        await self.db.commit()

        self.logger.info(
            f"Granted {FREE_TRIAL_SIGNUP_CREDIT_AMOUNT} trial credits to user {user_id} (organization {organization_id})"
        )
        return True

    async def get_usage_history(
        self, organization_id: UUID, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict], int]:
        """Get organization's credit consumption history from usage_records table."""
        stmt = (
            select(
                UsageRecord,
                Subscription.description.label("subscription_description"),
                TopUp.description.label("topup_description"),
            )
            .outerjoin(Subscription, UsageRecord.subscription_id == Subscription.id)
            .outerjoin(TopUp, UsageRecord.topup_id == TopUp.id)
            .where(UsageRecord.organization_id == organization_id)
            .order_by(UsageRecord.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        records = result.all()

        count_result = await self.db.execute(
            select(func.count(UsageRecord.id)).where(
                UsageRecord.organization_id == organization_id
            )
        )
        total_records = count_result.scalar() or 0

        records_data = [
            {
                "id": str(row.UsageRecord.id),
                "credits_consumed": abs(row.UsageRecord.credits_consumed),
                "api_key_id": (
                    str(row.UsageRecord.api_key_id)
                    if row.UsageRecord.api_key_id
                    else None
                ),
                "organization_id": str(row.UsageRecord.organization_id),
                "subscription_id": (
                    str(row.UsageRecord.subscription_id)
                    if row.UsageRecord.subscription_id
                    else None
                ),
                "topup_id": (
                    str(row.UsageRecord.topup_id) if row.UsageRecord.topup_id else None
                ),
                "description": row.topup_description or row.subscription_description,
                "created_at": row.UsageRecord.created_at.isoformat(),
            }
            for row in records
        ]

        return records_data, total_records

    async def get_credit_grants_history(
        self, organization_id: UUID, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict], int]:
        """Get organization's credit grants history with pagination."""
        total_result = await self.db.execute(
            select(func.count(CreditGrant.id)).where(
                CreditGrant.organization_id == organization_id
            )
        )
        total_grants = total_result.scalar() or 0

        result = await self.db.execute(
            select(CreditGrant)
            .where(CreditGrant.organization_id == organization_id)
            .order_by(CreditGrant.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        grants = result.scalars().all()

        grants_records = [
            {
                "id": str(grant.id),
                "grant_type": grant.grant_type,
                "description": grant.description,
                "amount": grant.amount,
                "remaining_amount": grant.remaining_amount,
                "expires_at": (
                    grant.expires_at.isoformat() if grant.expires_at else None
                ),
                "subscription_id": (
                    str(grant.subscription_id) if grant.subscription_id else None
                ),
                "topup_id": (str(grant.topup_id) if grant.topup_id else None),
                "created_at": grant.created_at.isoformat(),
            }
            for grant in grants
        ]

        return grants_records, total_grants

    async def get_credits_summary(self, organization_id: UUID) -> CreditsSummaryModel:
        """Get detailed credits breakdown including subscription, topups, and overage."""
        subscription_stmt = (
            select(Subscription)
            .where(
                and_(
                    Subscription.organization_id == organization_id,
                    Subscription.status == SubscriptionStatus.ACTIVE,
                )
            )
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        subscription_result = await self.db.execute(subscription_stmt)
        subscription = subscription_result.scalar_one_or_none()

        subscription_summary = None
        overage_summary = None
        subscription_credits_total = 0

        if subscription:
            sub_grants_stmt = select(CreditGrant).where(
                and_(
                    CreditGrant.subscription_id == subscription.id,
                    CreditGrant.grant_type == GrantType.SUBSCRIPTION,
                    CreditGrant.expires_at > datetime.now(timezone.utc),
                )
            )
            sub_grants_result = await self.db.execute(sub_grants_stmt)
            sub_grants = sub_grants_result.scalars().all()

            granted_this_period = sum(grant.amount for grant in sub_grants)
            remaining = sum(grant.remaining_amount for grant in sub_grants)
            subscription_credits_total = remaining

            usage_records_stmt = select(
                func.coalesce(func.sum(UsageRecord.credits_consumed), 0)
            ).where(
                and_(
                    UsageRecord.organization_id == organization_id,
                    UsageRecord.subscription_id == subscription.id,
                    UsageRecord.subscription_id.isnot(None),
                    UsageRecord.created_at >= subscription.current_period_start,
                    UsageRecord.created_at <= subscription.current_period_end,
                    UsageRecord.operation_type == OperationType.CONSUMPTION,
                )
            )
            usage_records_result = await self.db.execute(usage_records_stmt)
            used_this_period = usage_records_result.scalar() or 0

            billing_interval = "monthly"
            if subscription.stripe_price_base_id:
                from src.modules.billing.constants import SUBSCRIPTION_PACKAGES

                for package_key, package_info in SUBSCRIPTION_PACKAGES.items():
                    if package_info.base_price_id == subscription.stripe_price_base_id:
                        package_name = (
                            package_key.value
                            if hasattr(package_key, "value")
                            else str(package_key)
                        )
                        billing_interval = (
                            "yearly" if "YEARLY" in package_name.upper() else "monthly"
                        )
                        break

            subscription_summary = SubscriptionCreditsSummaryModel(
                id=str(subscription.id),
                monthly_allowance=subscription.monthly_allowance,
                granted_this_period=granted_this_period,
                used_this_period=used_this_period,
                remaining=remaining,
                period_start=subscription.current_period_start,
                period_end=subscription.current_period_end,
                status=subscription.status,
                billing_interval=billing_interval,
                price_paid=subscription.price_paid,
                overage_unit_price=float(subscription.overage_unit_price),
                cancel_at_period_end=subscription.cancel_at_period_end,
                pause_access=subscription.pause_access,
            )

            usage_period_stmt = (
                select(UsagePeriod)
                .where(
                    and_(
                        UsagePeriod.subscription_id == subscription.id,
                        not_(UsagePeriod.closed),
                    )
                )
                .order_by(UsagePeriod.created_at.desc())
                .limit(1)
            )
            usage_period_result = await self.db.execute(usage_period_stmt)
            usage_period = usage_period_result.scalar_one_or_none()

            if usage_period:
                if not subscription.overage_enabled:
                    effective_cap: int | None = 0
                    remaining_until_cap: int | None = 0
                else:
                    effective_cap = (
                        subscription.user_extra_cap
                        if subscription.user_extra_cap is not None
                        else None
                    )
                    remaining_until_cap = (
                        (effective_cap - usage_period.overage_used)
                        if effective_cap is not None
                        else None
                    )

                overage_summary = OverageSummaryModel(
                    enabled=subscription.overage_enabled,
                    used=usage_period.overage_used,
                    reported_to_stripe=usage_period.overage_reported,
                    cap=effective_cap,
                    remaining_until_cap=remaining_until_cap,
                    unit_price=subscription.overage_unit_price,
                )

        topup_grants_stmt = (
            select(CreditGrant, TopUp)
            .join(TopUp, CreditGrant.topup_id == TopUp.id)
            .where(
                and_(
                    CreditGrant.organization_id == organization_id,
                    CreditGrant.grant_type.in_([GrantType.TOPUP, GrantType.TRIAL]),
                    CreditGrant.remaining_amount > 0,
                    or_(
                        CreditGrant.expires_at.is_(None),
                        CreditGrant.expires_at > datetime.now(timezone.utc),
                    ),
                )
            )
            .order_by(CreditGrant.expires_at.asc().nulls_last())
        )
        topup_result = await self.db.execute(topup_grants_stmt)
        topup_data = topup_result.all()

        topups_summary = []
        topup_credits_total = 0

        for grant, topup in topup_data:
            used = grant.amount - grant.remaining_amount
            topup_credits_total += grant.remaining_amount

            topups_summary.append(
                TopupCreditSummaryModel(
                    id=str(grant.id),
                    name=grant.description,
                    granted=grant.amount,
                    used=used,
                    remaining=grant.remaining_amount,
                    expires_at=grant.expires_at,
                    purchased_at=topup.created_at,
                )
            )

        overage_credits = overage_summary.used if overage_summary else 0
        total_available = subscription_credits_total + topup_credits_total

        summary_totals = CreditsSummaryTotalsModel(
            total_available=total_available,
            subscription_credits=subscription_credits_total,
            topup_credits=topup_credits_total,
            overage_credits=overage_credits,
        )

        return CreditsSummaryModel(
            subscription=subscription_summary,
            overage=overage_summary,
            topups=topups_summary,
            summary=summary_totals,
        )
