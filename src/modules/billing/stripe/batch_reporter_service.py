from datetime import datetime
import stripe
from sqlalchemy import select

from src.database.models import Subscription, UsagePeriod
from src.core.base import BaseService
from src.modules.billing.constants import STRIPE_METER_EVENT_NAME


class BatchReporterService(BaseService):
    """Service for batch reporting usage to Stripe."""

    async def report_usage_to_stripe(self):
        """Report accumulated overage usage to Stripe for all open usage periods."""
        try:
            # Get all open usage periods
            stmt = select(UsagePeriod).where(not UsagePeriod.closed)
            result = await self.db.execute(stmt)
            usage_periods = result.scalars().all()

            for period in usage_periods:
                await self._report_period_usage(period)

            await self.db.commit()
        except Exception as e:
            self.logger.error("Error in batch reporter", error=str(e))
            # Don't commit if there was an error

    async def _report_period_usage(self, usage_period):
        """Report usage for a single period to Stripe."""
        # Calculate delta since last report
        delta = usage_period.overage_used - usage_period.overage_reported

        if delta <= 0:
            return

        # Get subscription to find Stripe item ID
        stmt = select(Subscription).where(
            Subscription.id == usage_period.subscription_id
        )
        result = await self.db.execute(stmt)
        subscription = result.scalar_one_or_none()

        if not subscription or not subscription.stripe_item_overage_id:
            return

        try:
            # Report usage to Stripe using Billing Meters API
            stripe.billing.MeterEvent.create(
                event_name=STRIPE_METER_EVENT_NAME,
                payload={
                    "stripe_customer_id": subscription.stripe_customer_id,
                    "value": str(delta),
                },
                timestamp=int(datetime.now().timestamp()),
            )

            # Update reported amount
            usage_period.overage_reported += delta

        except stripe.StripeError as e:
            self.logger.error(
                "Failed to report usage to Stripe",
                subscription_id=str(subscription.id),
                error=str(e),
            )
