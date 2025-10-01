"""Credit management service with dependency injection."""

from datetime import datetime, timezone, timedelta
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
    CreditGrant,
    GrantType,
    TopUp,
    OperationType,
    Subscription,
    SubscriptionStatus,
    UsagePeriod,
    UsageRecord,
    UsageType,
)
from src.core.base import BaseService
from src.utils.logger import get_logger

logger = get_logger(__name__)


class PredictionCreditService(BaseService):
    """Service for credit management operations."""

    async def get_organization_credits(self, organization_id: UUID) -> tuple[int, int]:
        """Get available credits for organization - subscription and top-up amounts."""

        subscription_credits = 0
        top_up_credits = 0

        grant_breakdown_stmt = (
            select(CreditGrant.grant_type, func.sum(CreditGrant.remaining_amount))
            .where(
                CreditGrant.organization_id == organization_id,
                CreditGrant.remaining_amount > 0,
            )
            .group_by(CreditGrant.grant_type)
        )
        grant_breakdown_result = await self.db.execute(grant_breakdown_stmt)
        for grant_type, amount in grant_breakdown_result:
            if grant_type == "subscription":
                subscription_credits = amount or 0
            else:  # topup, trial, manual
                top_up_credits += amount or 0

        return (
            subscription_credits,
            top_up_credits,
        )

    async def _update_credit_grants(
        self, organization_id: UUID, credits_consumed: int
    ) -> list[dict]:
        """Update credit grants usage. Returns list of grant details used."""
        # Get active credit grants (not expired, with remaining credits)
        grant_stmt = (
            select(CreditGrant)
            .where(
                CreditGrant.organization_id == organization_id,
                CreditGrant.remaining_amount > 0,
            )
            .order_by(CreditGrant.created_at.asc())
        )  # FIFO - oldest first
        grant_result = await self.db.execute(grant_stmt)
        grants = grant_result.scalars().all()

        remaining_credits = credits_consumed
        used_grants = []
        now = datetime.now(timezone.utc)

        for grant in grants:
            # Only consume from grants that haven't expired
            if not grant.expires_at or grant.expires_at > now:
                if grant.remaining_amount > 0:
                    credits_from_grant = min(remaining_credits, grant.remaining_amount)
                    grant.remaining_amount -= credits_from_grant
                    remaining_credits -= credits_from_grant
                    used_grants.append(
                        {
                            "id": grant.id,
                            "grant_type": grant.grant_type,
                            "subscription_id": grant.subscription_id,
                            "topup_id": grant.topup_id,
                            "credits_used": credits_from_grant,
                        }
                    )

                    if remaining_credits <= 0:
                        break

        if remaining_credits > 0:
            self.logger.warning(
                f"Could not consume all {credits_consumed} credits from grants for organization {organization_id}. "
                f"Consumed {credits_consumed - remaining_credits} credits from {len(used_grants)} grants."
            )

        return used_grants

    async def consume_credits(
        self,
        organization_id: UUID,
        credits_to_consume: int,
        user_id: UUID | None = None,
        api_key_id: UUID | None = None,
        usage_type: UsageType = UsageType.GEOINFER_GLOBAL_0_0_1,
    ) -> bool:
        """
        Consume credits for an organization (user or API key)."""
        # organization_id must always be provided
        if not organization_id:
            self.logger.error("organization_id must be provided")
            return False

        # Check available credits for the organization
        subscription_credits, top_up_credits = await self.get_organization_credits(
            organization_id=organization_id
        )
        available_credits = subscription_credits + top_up_credits

        # Check if enough credits available
        if available_credits < credits_to_consume:
            return False

        # Use the new credit grant system
        used_grants = await self._update_credit_grants(
            organization_id, credits_to_consume
        )

        # If we couldn't consume all credits, return false
        if len(used_grants) == 0:
            self.logger.error(
                f"Could not consume any credits for organization {organization_id}"
            )
            return False

        # Create usage records - one for each grant type used
        for grant_info in used_grants:
            usage_record = UsageRecord(
                user_id=user_id,
                organization_id=organization_id,
                credits_consumed=grant_info["credits_used"],
                usage_type=UsageType.GEOINFER_GLOBAL_0_0_1,
                operation_type=OperationType.CONSUMPTION,
                api_key_id=api_key_id,
                subscription_id=grant_info["subscription_id"],
                topup_id=grant_info["topup_id"],
            )
            self.db.add(usage_record)

        await self.db.commit()

        if user_id:
            self.logger.info(
                f"Consumed {credits_to_consume} credits for user {user_id}"
            )
        else:
            self.logger.info(
                f"Consumed {credits_to_consume} credits for organization {organization_id} via API key"
            )
        return True

    async def grant_trial_credits_to_user(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> bool:
        """
        Grant trial credits to a new user.

        Args:
            organization_id: Organization ID
            user_id: User ID for tracking

        Returns:
            True if trial credits were granted successfully
        """
        # Check if user already has trial credits
        trial_topup_stmt = select(TopUp).where(
            TopUp.organization_id == organization_id,
            TopUp.stripe_payment_intent_id.is_(None),  # Manual/trial grants
        )
        trial_topup_result = await self.db.execute(trial_topup_stmt)
        trial_topups = trial_topup_result.scalars().all()

        # Check if user already has trial credits
        for topup in trial_topups:
            if topup.package_type == GrantType.TRIAL:
                self.logger.info(f"User {user_id} already has trial credits")
                return True  # Already has trial credits

        trial_expiry = datetime.now(timezone.utc) + timedelta(
            days=TRIAL_CREDIT_EXPIRY_DAYS
        )

        # Grant trial credits that expire after 15 days
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

        # Create the corresponding credit grant
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

        # Get total count
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
        # Get total count
        total_result = await self.db.execute(
            select(func.count(CreditGrant.id)).where(
                CreditGrant.organization_id == organization_id
            )
        )
        total_grants = total_result.scalar() or 0

        # Get paginated grants
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
        # Get active subscription
        subscription_stmt = select(Subscription).where(
            and_(
                Subscription.organization_id == organization_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
        )
        subscription_result = await self.db.execute(subscription_stmt)
        subscription = subscription_result.scalar_one_or_none()

        subscription_summary = None
        overage_summary = None
        subscription_credits_total = 0

        if subscription:
            # Get subscription credit grants for current period
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
            used_this_period = granted_this_period - remaining
            subscription_credits_total = remaining

            # Determine billing interval from stripe price ID
            billing_interval = "monthly"  # default
            if subscription.stripe_price_base_id:
                from src.modules.billing.constants import SUBSCRIPTION_PACKAGES

                for package_key, package_info in SUBSCRIPTION_PACKAGES.items():
                    if package_info.base_price_id == subscription.stripe_price_base_id:
                        # Determine interval from package key (e.g., PRO_MONTHLY, PRO_YEARLY)
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

            # Get current usage period for overage info
            usage_period_stmt = select(UsagePeriod).where(
                and_(
                    UsagePeriod.subscription_id == subscription.id,
                    not_(UsagePeriod.closed),
                )
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
                        if subscription.user_extra_cap
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

        # Get active topups (including trial credits)
        topup_grants_stmt = (
            select(CreditGrant, TopUp)
            .join(TopUp, CreditGrant.topup_id == TopUp.id)
            .where(
                and_(
                    CreditGrant.organization_id == organization_id,
                    CreditGrant.grant_type.in_([GrantType.TOPUP, GrantType.TRIAL]),
                    CreditGrant.remaining_amount > 0,
                    # Include credits that either don't expire or haven't expired yet
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

        # Calculate totals
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
