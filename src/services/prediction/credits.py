"""Credit management service with dependency injection."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, func

from src.api.core.constants import FREE_TRIAL_SIGNUP_CREDIT_AMOUNT
from src.database.models import (
    CreditGrant,
    GrantType,
    TopUp,
    OperationType,
    Subscription,
    UsageRecord,
    UsageType,
)
from src.services.base import BaseService
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

        # Check if user already has trial credits (no expiration date)
        for topup in trial_topups:
            if not topup.expires_at:
                self.logger.info(f"User {user_id} already has trial credits")
                return True  # Already has trial credits

        # Grant trial credits that never expire
        trial_topup = TopUp(
            organization_id=organization_id,
            credits_purchased=FREE_TRIAL_SIGNUP_CREDIT_AMOUNT,
            description="Geoinfer Trial Credits",
            stripe_payment_intent_id=None,
            price_paid=0.0,
            package_type=GrantType.TRIAL,
            expires_at=None,
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
            expires_at=None,
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
