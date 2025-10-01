"""Stripe payment management service with comprehensive webhook handling."""

from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

import stripe  # type: ignore
from stripe import StripeError  # type: ignore
from sqlalchemy import select, and_


from src.database.models import (
    Subscription,
    SubscriptionStatus,
    TopUp,
    CreditGrant,
    GrantType,
    UsagePeriod,
    Organization,
    PlanTier,
)
from src.core.base import BaseService
from src.utils.settings.stripe import StripeSettings
from src.modules.billing.constants import (
    SUBSCRIPTION_PACKAGES,
    TOPUP_PACKAGES,
    StripeProductType,
    SubscriptionPackage,
    TopupPackage,
    SubscriptionPackageConfig,
    STRIPE_METER_EVENT_NAME,
    STRIPE_PORTAL_CONFIGURATION_ID,
    PRICE_TO_PLAN_TIER,
)


class StripePaymentService(BaseService):
    def __init__(self, db):
        super().__init__(db)
        stripe.api_key = StripeSettings().STRIPE_SECRET_KEY.get_secret_value()

    def get_subscription_package_config(self, package: SubscriptionPackage) -> dict:
        return SUBSCRIPTION_PACKAGES.get(package, {})

    def get_topup_package_config(self, package: TopupPackage) -> dict:
        return TOPUP_PACKAGES.get(package, {})

    def get_plan_tier_from_subscription(self, subscription: Subscription) -> PlanTier:
        price_id = subscription.stripe_price_base_id
        if price_id and price_id in PRICE_TO_PLAN_TIER:
            return PRICE_TO_PLAN_TIER[price_id]
        return PlanTier.SUBSCRIBED

    async def _find_subscription_by_stripe_id(
        self, stripe_subscription_id: str
    ) -> Subscription | None:
        """Find subscription by Stripe subscription ID."""
        stmt = select(Subscription).where(
            Subscription.stripe_subscription_id == stripe_subscription_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_subscription_organization(
        self, subscription: Subscription
    ) -> Organization | None:
        """Get organization for a subscription."""
        return await self.db.get(Organization, subscription.organization_id)

    async def _update_organization_plan_tier(
        self,
        organization: Organization,
        subscription: Subscription,
        force_free: bool = False,
    ) -> None:
        """Update organization plan tier based on subscription status.

        Args:
            organization: Organization to update
            subscription: Related subscription
            force_free: If True, set to FREE regardless of subscription tier
        """
        if force_free:
            if organization.plan_tier != PlanTier.FREE:
                organization.plan_tier = PlanTier.FREE
                self.logger.info(
                    f"Downgraded organization {organization.id} to FREE tier"
                )
        else:
            target_plan_tier = self.get_plan_tier_from_subscription(subscription)
            if organization.plan_tier != target_plan_tier:
                organization.plan_tier = target_plan_tier
                self.logger.info(
                    f"Updated organization {organization.id} plan_tier to {target_plan_tier.value}"
                )

        await self.db.commit()

    def _extract_subscription_items(
        self, subscription_data: dict
    ) -> tuple[str | None, str | None]:
        items = subscription_data.get("items", {}).get("data", [])
        base_price_id = None
        overage_price_id = None

        for item in items:
            price_id = item["price"]["id"]
            if item["price"].get("recurring", {}).get("usage_type") == "metered":
                overage_price_id = price_id
            else:
                base_price_id = price_id

        return base_price_id, overage_price_id

    async def _find_or_create_stripe_customer(
        self, organization: Organization, customer_email: str
    ) -> str:
        """Find or create a Stripe customer for the organization.

        Returns the Stripe customer ID, ensuring one customer per organization.
        Most organizations should already have a customer from onboarding.
        """
        # If organization already has a customer ID, verify it exists in Stripe
        if organization.stripe_customer_id:
            try:
                customer = stripe.Customer.retrieve(organization.stripe_customer_id)
                if customer and not customer.get("deleted"):
                    self.logger.debug(
                        f"Using existing Stripe customer {organization.stripe_customer_id} for organization {organization.id}"
                    )
                    return organization.stripe_customer_id
                else:
                    self.logger.warning(
                        f"Stripe customer {organization.stripe_customer_id} not found or deleted, creating new one"
                    )
            except StripeError as e:
                self.logger.warning(
                    f"Error retrieving Stripe customer {organization.stripe_customer_id}: {e}, creating new one"
                )

        # Fallback: Create new customer (should be rare since onboarding creates customers)
        try:
            customer = stripe.Customer.create(
                email=customer_email,
                name=organization.name,
                metadata={
                    "organization_id": str(organization.id),
                    "organization_name": organization.name,
                },
            )

            # Store customer ID in organization
            organization.stripe_customer_id = customer.id
            await self.db.commit()

            self.logger.info(
                f"Created fallback Stripe customer {customer.id} for organization {organization.id} (should have been created during onboarding)"
            )
            return customer.id

        except StripeError as e:
            raise ValueError(f"Failed to create Stripe customer: {e}")

    async def create_checkout_session(
        self,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        organization_id: UUID,
        product_type: StripeProductType = StripeProductType.SUBSCRIPTION,
    ) -> stripe.checkout.Session:
        try:
            # Build line items with only the base price
            # Note: Overage metered prices will be added to the subscription
            # after creation via webhook to avoid Stripe billing interval conflicts
            line_items = [{"price": price_id, "quantity": 1}]

            checkout_session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=line_items,
                mode=(
                    "subscription"
                    if product_type == StripeProductType.SUBSCRIPTION
                    else "payment"
                ),
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "organization_id": str(organization_id),
                    "product_type": product_type.value,
                },
                allow_promotion_codes=True,
            )
            return checkout_session
        except StripeError as e:
            raise ValueError(f"Failed to create checkout session: {e}")

    async def create_customer_portal_session(
        self, customer_id: str, return_url: str
    ) -> stripe.billing_portal.Session:
        try:
            portal_session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
                configuration=STRIPE_PORTAL_CONFIGURATION_ID,
            )
            return portal_session
        except StripeError as e:
            raise ValueError(f"Failed to create portal session: {e}")

    def validate_webhook_signature(self, payload: bytes, signature: str) -> dict:
        try:
            event = stripe.Webhook.construct_event(
                payload,
                signature,
                StripeSettings().STRIPE_WEBHOOK_SECRET,
            )
            return event
        except Exception:
            raise ValueError("Invalid webhook data")

    async def handle_webhook_event(self, event: dict) -> bool:
        """Handle all Stripe webhook events comprehensively."""
        event_type = event["type"]
        data = event["data"]["object"]

        webhook_handlers = {
            "checkout.session.completed": self._handle_checkout_completed,
            "customer.subscription.created": self._handle_subscription_created,
            "customer.subscription.updated": self._handle_subscription_updated,
            "customer.subscription.deleted": self._handle_subscription_deleted,
            "invoice.finalized": self._handle_invoice_finalized,
            "invoice.paid": self._handle_invoice_paid,
            "invoice.payment_failed": self._handle_invoice_payment_failed,
            "charge.refunded": self._handle_charge_refunded,
        }

        handler = webhook_handlers.get(event_type)
        if not handler:
            return False

        try:
            await handler(data)
            return True
        except Exception as e:
            self.logger.error(
                "Error handling webhook", event_type=event_type, error=str(e)
            )
            return False

    async def _handle_checkout_completed(self, session_data: dict) -> None:
        """Handle successful checkout completion."""
        mode = session_data.get("mode")
        metadata = session_data.get("metadata", {})

        # Get organization_id from metadata
        organization_id_str = metadata.get("organization_id")
        if not organization_id_str:
            self.logger.warning("No organization_id in checkout session metadata")
            return

        try:
            organization_id = UUID(organization_id_str)
        except (ValueError, TypeError):
            self.logger.error(
                f"Invalid organization_id in metadata: {organization_id_str}"
            )
            return

        # Get organization from database
        stmt = select(Organization).where(Organization.id == organization_id)
        result = await self.db.execute(stmt)
        organization = result.scalar_one_or_none()

        if not organization:
            self.logger.error(f"Organization not found: {organization_id}")
            return

        # Retrieve line items from Stripe (not included in webhook by default)
        session_id = session_data.get("id")
        try:
            session = stripe.checkout.Session.retrieve(
                session_id, expand=["line_items"]
            )
            line_items = session.get("line_items", {}).get("data", [])
        except StripeError as e:
            self.logger.error(
                f"Failed to retrieve line items for session {session_id}: {e}"
            )
            return

        for item in line_items:
            price_id = item["price"]["id"]

            if mode == "subscription":
                await self._process_subscription_checkout(
                    organization, session_data, price_id
                )
            elif mode == "payment":
                await self._process_topup_checkout(organization, session_data, price_id)

    async def _process_subscription_checkout(
        self, organization, session_data, price_id: str
    ) -> None:
        """Process subscription creation from checkout.

        Creates a minimal subscription record to link organization to Stripe subscription.
        The customer.subscription.created event will update with full billing details.
        """
        subscription_id = session_data.get("subscription")
        if not subscription_id:
            return

        # Find the matching subscription package
        subscription_package = None
        for package, package_info in SUBSCRIPTION_PACKAGES.items():
            if package_info.base_price_id == price_id:
                subscription_package = package
                break

        if not subscription_package:
            return

        package_info = SUBSCRIPTION_PACKAGES[subscription_package]
        customer_id = session_data.get("customer")

        # Create minimal subscription record to establish org link
        # Period fields will be updated when customer.subscription.created fires
        stmt = select(Subscription).where(
            Subscription.stripe_subscription_id == subscription_id
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        if not existing:
            # Use current time as temporary values - will be updated by subscription.created
            now = datetime.now(timezone.utc)
            subscription = Subscription(
                id=uuid4(),
                organization_id=organization.id,
                stripe_subscription_id=subscription_id,
                stripe_customer_id=customer_id,
                description=package_info.name,
                price_paid=0.0,  # Will be updated by customer.subscription.created
                monthly_allowance=package_info.monthly_allowance,
                overage_unit_price=package_info.overage_unit_price,
                status=SubscriptionStatus.ACTIVE,
                overage_enabled=False,
                current_period_start=now,
                current_period_end=now,
            )
            self.db.add(subscription)
            await self.db.commit()
            self.logger.info(
                f"Created minimal subscription record for {subscription_id}, "
                f"will be updated by customer.subscription.created"
            )

        # Add overage metered price if package has one
        if package_info.overage_price_id:
            try:
                stripe_subscription = stripe.Subscription.retrieve(subscription_id)
                items = stripe_subscription.get("items", {}).get("data", [])
                has_overage_price = any(
                    item["price"].get("recurring", {}).get("usage_type") == "metered"
                    for item in items
                )

                if not has_overage_price:
                    stripe.SubscriptionItem.create(
                        subscription=subscription_id,
                        price=package_info.overage_price_id,
                        proration_behavior="none",
                    )
                    self.logger.info(
                        f"Added overage price {package_info.overage_price_id} to subscription {subscription_id}"
                    )
            except StripeError as e:
                self.logger.error(
                    f"Failed to add overage price to subscription {subscription_id}: {e}"
                )

    async def _process_topup_checkout(
        self, organization, session_data, price_id: str
    ) -> None:
        """Process topup package purchase from checkout."""
        # Find the matching topup package
        topup_package = None
        for package, package_info in TOPUP_PACKAGES.items():
            if package_info.price_id == price_id:
                topup_package = package
                break

        if not topup_package:
            self.logger.warning(f"No topup package found for price_id: {price_id}")
            return

        package_info = TOPUP_PACKAGES[topup_package]

        self.logger.info(
            f"Processing topup checkout for organization {organization.id}: "
            f"{package_info.name} ({package_info.credits} credits)"
        )

        # Create top-up
        topup = TopUp(
            id=uuid4(),
            organization_id=organization.id,
            stripe_payment_intent_id=session_data.get("payment_intent"),
            description=package_info.name,
            price_paid=float(package_info.price),
            credits_purchased=package_info.credits,
            package_type=GrantType.TOPUP,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=package_info.expiry_days),
        )
        self.db.add(topup)
        await self.db.commit()

        # Create credit grant
        credit_grant = CreditGrant(
            id=uuid4(),
            organization_id=organization.id,
            topup_id=topup.id,
            grant_type=GrantType.TOPUP,
            description=package_info.name,
            amount=package_info.credits,
            remaining_amount=package_info.credits,
            expires_at=topup.expires_at,
        )
        self.db.add(credit_grant)
        await self.db.commit()

        self.logger.info(
            f"Successfully created credit grant {credit_grant.id} for "
            f"organization {organization.id}: {package_info.credits} credits"
        )

    async def _handle_subscription_created(self, subscription_data: dict) -> None:
        """Handle subscription creation (outside checkout).

        This may fire before or after checkout.session.completed, so we check
        both by customer_id and by subscription_id to find the organization.
        """
        subscription_id = subscription_data["id"]
        customer_id = subscription_data["customer"]

        # Try to find organization via customer_id first
        organization = await self._get_organization_by_stripe_customer(customer_id)

        # If not found, check if minimal subscription was created by checkout
        if not organization:
            stmt = select(Subscription).where(
                Subscription.stripe_subscription_id == subscription_id
            )
            result = await self.db.execute(stmt)
            existing_subscription = result.scalar_one_or_none()

            if existing_subscription:
                stmt = select(Organization).where(
                    Organization.id == existing_subscription.organization_id
                )
                result = await self.db.execute(stmt)
                organization = result.scalar_one_or_none()

        if not organization:
            # This is expected for new customers where subscription.created fires before
            # checkout.session.completed. The subscription will be properly set up when
            # checkout completes and provides the organization_id in metadata.
            self.logger.info(
                f"Organization not yet linked for subscription {subscription_id} "
                f"(customer {customer_id}). Will be processed when checkout.session.completed fires."
            )
            return

        # Find plan from items and capture all item IDs
        items = subscription_data.get("items", {}).get("data", [])
        if not items:
            return

        base_price_id = None
        for item in items:
            price_id = item["price"]["id"]
            if item["price"].get("recurring", {}).get("usage_type") == "metered":
                # Found overage price - skip for now, will be captured below
                pass
            else:
                base_price_id = price_id

        if not base_price_id:
            return

        # Find subscription package
        subscription_package = None
        for package, package_info in SUBSCRIPTION_PACKAGES.items():
            if package_info.base_price_id == base_price_id:
                subscription_package = package
                break

        if not subscription_package:
            return

        package_info = SUBSCRIPTION_PACKAGES[subscription_package]

        try:
            subscription = await self._find_or_create_subscription(
                organization.id,
                subscription_data["id"],
                package_info,
                subscription_data,
            )
        except ValueError as e:
            self.logger.warning(str(e))
            return

        # Capture subscription item IDs for both base and overage
        has_overage_price = False
        for item in items:
            price_id = item["price"]["id"]
            if item["price"].get("recurring", {}).get("usage_type") == "metered":
                subscription.stripe_item_overage_id = item["id"]
                subscription.stripe_price_overage_id = price_id
                has_overage_price = True
            else:
                subscription.stripe_item_base_id = item["id"]
                subscription.stripe_price_base_id = price_id

        # Add overage metered price if not already present (check both current items and DB state)
        needs_overage = (
            not has_overage_price
            and not subscription.stripe_item_overage_id
            and package_info.overage_price_id
        )
        if needs_overage:
            try:
                subscription_item = stripe.SubscriptionItem.create(
                    subscription=subscription_data["id"],
                    price=package_info.overage_price_id,
                    proration_behavior="none",
                )
                subscription.stripe_item_overage_id = subscription_item["id"]
                subscription.stripe_price_overage_id = package_info.overage_price_id
                self.logger.info(
                    f"Added overage price {package_info.overage_price_id} to subscription {subscription_data['id']}"
                )
            except StripeError as e:
                self.logger.error(
                    f"Failed to add overage price to subscription {subscription_data['id']}: {e}"
                )

        await self.db.commit()

        # Update organization plan_tier based on subscription
        await self._update_organization_plan_tier(organization, subscription)

        # Create usage period and credit grants (idempotent)
        await self._create_usage_period(subscription)

    async def _handle_subscription_updated(self, subscription_data: dict) -> None:
        """Handle subscription updates."""
        subscription_id = subscription_data["id"]
        subscription = await self._find_subscription_by_stripe_id(subscription_id)

        if not subscription:
            return

        # Store old period_end to detect billing period changes (renewals)
        old_period_end = subscription.current_period_end

        # Extract period fields from subscription items if not at root level
        current_period_start = subscription_data.get("current_period_start")
        current_period_end = subscription_data.get("current_period_end")

        if not current_period_start or not current_period_end:
            # Try to get from first subscription item
            items = subscription_data.get("items", {}).get("data", [])
            if items:
                first_item = items[0]
                current_period_start = first_item.get("current_period_start")
                current_period_end = first_item.get("current_period_end")

        # Map Stripe status to our status
        stripe_status = subscription_data["status"]
        cancel_at_period_end = subscription_data.get("cancel_at_period_end", False)

        if stripe_status == "active":
            subscription.status = SubscriptionStatus.ACTIVE
        elif stripe_status == "past_due":
            subscription.status = SubscriptionStatus.PAST_DUE
        elif stripe_status == "canceled":
            subscription.status = SubscriptionStatus.CANCELLED
        elif stripe_status == "unpaid":
            subscription.status = SubscriptionStatus.UNPAID
        elif stripe_status == "incomplete_expired":
            subscription.status = SubscriptionStatus.INCOMPLETE_EXPIRED
        elif stripe_status == "trialing":
            subscription.status = SubscriptionStatus.TRIALING
        else:
            subscription.status = SubscriptionStatus.INACTIVE

        # Track if subscription is scheduled to cancel at period end
        subscription.cancel_at_period_end = cancel_at_period_end

        # Check for billing period fields and detect if period changed
        period_changed = False
        if current_period_start and current_period_end:
            new_period_end = datetime.fromtimestamp(current_period_end, timezone.utc)
            period_changed = new_period_end != old_period_end

            subscription.current_period_start = datetime.fromtimestamp(
                current_period_start, timezone.utc
            )
            subscription.current_period_end = new_period_end

        # Update organization plan_tier based on subscription status
        organization = await self._get_subscription_organization(subscription)
        if organization:
            # Determine if we should downgrade to FREE or maintain/upgrade tier
            should_downgrade = subscription.status in [
                SubscriptionStatus.CANCELLED,
                SubscriptionStatus.UNPAID,
                SubscriptionStatus.INCOMPLETE_EXPIRED,
            ]

            if should_downgrade:
                await self._update_organization_plan_tier(
                    organization, subscription, force_free=True
                )
            elif subscription.status in [
                SubscriptionStatus.ACTIVE,
                SubscriptionStatus.TRIALING,
            ]:
                # Active subscriptions get their target tier (even if scheduled to cancel later)
                await self._update_organization_plan_tier(organization, subscription)

                if cancel_at_period_end:
                    self.logger.info(
                        f"Subscription {subscription_id} is scheduled to cancel at period end. "
                        f"Organization {organization.id} will remain at current tier until {subscription.current_period_end}"
                    )
            elif subscription.status == SubscriptionStatus.PAST_DUE:
                self.logger.warning(
                    f"Subscription {subscription_id} is past due. "
                    f"Organization {organization.id} maintaining current tier temporarily."
                )

        # Update plan if price changed
        items = subscription_data.get("items", {}).get("data", [])
        for item in items:
            price_id = item["price"]["id"]
            if item["price"].get("recurring", {}).get("usage_type") == "metered":
                subscription.stripe_item_overage_id = item["id"]
                subscription.stripe_price_overage_id = price_id
            else:
                subscription.stripe_item_base_id = item["id"]
                subscription.stripe_price_base_id = price_id

                # Update subscription package info if price changed
                for package, package_info in SUBSCRIPTION_PACKAGES.items():
                    if package_info.base_price_id == price_id:
                        subscription.monthly_allowance = package_info.monthly_allowance
                        subscription.overage_unit_price = (
                            package_info.overage_unit_price
                        )
                        break

        await self.db.commit()

        # Only create new usage period if the billing period has changed (renewal)
        if period_changed:
            self.logger.info(
                f"Billing period changed for subscription {subscription_id}, creating new usage period"
            )
            await self._create_usage_period(subscription)

    async def _handle_subscription_deleted(self, subscription_data: dict) -> None:
        """Handle subscription cancellation."""
        subscription_id = subscription_data["id"]
        subscription = await self._find_subscription_by_stripe_id(subscription_id)

        if not subscription:
            return

        subscription.status = SubscriptionStatus.CANCELLED
        subscription.pause_access = True
        subscription.cancel_at_period_end = False

        # Downgrade organization to FREE tier
        organization = await self._get_subscription_organization(subscription)
        if organization:
            await self._update_organization_plan_tier(
                organization, subscription, force_free=True
            )

    async def _handle_invoice_finalized(self, invoice_data: dict) -> None:
        """Handle invoice finalization - report final usage to Stripe."""
        subscription_id = invoice_data.get("subscription")
        if not subscription_id:
            return

        stmt = select(Subscription).where(
            Subscription.stripe_subscription_id == subscription_id
        )
        result = await self.db.execute(stmt)
        subscription = result.scalar_one_or_none()

        if not subscription:
            return

        # Get current usage period
        stmt = (
            select(UsagePeriod)
            .where(
                and_(
                    UsagePeriod.subscription_id == subscription.id,
                    not UsagePeriod.closed,
                )
            )
            .order_by(UsagePeriod.created_at.desc())
        )
        result = await self.db.execute(stmt)
        usage_period = result.scalar_one_or_none()

        if not usage_period:
            return

        # Calculate delta and report to Stripe
        delta = usage_period.overage_used - usage_period.overage_reported
        if delta > 0:
            try:
                stripe.billing.MeterEvent.create(
                    event_name=STRIPE_METER_EVENT_NAME,
                    payload={
                        "stripe_customer_id": subscription.stripe_customer_id,
                        "value": str(delta),
                    },
                    timestamp=int(datetime.now().timestamp()),
                )
                usage_period.overage_reported += delta
            except StripeError as e:
                self.logger.error(
                    "Failed to report usage to Stripe",
                    subscription_id=str(subscription.id),
                    error=str(e),
                )

        # Close current period and create next
        usage_period.closed = True

        # Create next period
        next_period_start = datetime.fromtimestamp(
            invoice_data.get(
                "period_start", subscription.current_period_start.timestamp()
            ),
            timezone.utc,
        )
        next_period_end = datetime.fromtimestamp(
            invoice_data.get("period_end", subscription.current_period_end.timestamp()),
            timezone.utc,
        )

        next_usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=next_period_start,
            period_end=next_period_end,
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        self.db.add(next_usage_period)

        # Seed new monthly credit grant (only if access is not paused)
        if not subscription.pause_access:
            credit_grant = CreditGrant(
                id=uuid4(),
                organization_id=subscription.organization_id,
                subscription_id=subscription.id,
                grant_type=GrantType.SUBSCRIPTION,
                description=f"Monthly Subscription Credits - {next_period_start.strftime('%B %Y')}",
                amount=subscription.monthly_allowance,
                remaining_amount=subscription.monthly_allowance,
                expires_at=next_period_end,
            )
            self.db.add(credit_grant)
            self.logger.info(
                f"Created monthly credit grant of {subscription.monthly_allowance} credits for subscription {subscription.id}"
            )
        else:
            self.logger.warning(
                f"Skipped credit grant creation for subscription {subscription.id} - access is paused due to payment issues"
            )

        await self.db.commit()

    async def _handle_invoice_paid(self, invoice_data: dict) -> None:
        """Handle successful invoice payment - restore access and tier if needed."""
        subscription_id = invoice_data.get("subscription")
        if not subscription_id:
            return

        subscription = await self._find_subscription_by_stripe_id(subscription_id)
        if not subscription:
            return

        # Restore access
        was_paused = subscription.pause_access
        subscription.pause_access = False

        # If was PAST_DUE, mark as ACTIVE
        if subscription.status == SubscriptionStatus.PAST_DUE:
            subscription.status = SubscriptionStatus.ACTIVE
            self.logger.info(
                f"Subscription {subscription_id} recovered from PAST_DUE to ACTIVE"
            )

        # If access was paused, create missed credit grants for current period
        if was_paused:
            await self._create_missed_credit_grants(subscription)

        # Restore plan tier based on subscription
        organization = await self._get_subscription_organization(subscription)
        if organization and subscription.status == SubscriptionStatus.ACTIVE:
            await self._update_organization_plan_tier(organization, subscription)

    async def _handle_invoice_payment_failed(self, invoice_data: dict) -> None:
        """Handle failed invoice payment."""
        subscription_id = invoice_data.get("subscription")
        if not subscription_id:
            return

        subscription = await self._find_subscription_by_stripe_id(subscription_id)
        if not subscription:
            return

        subscription.pause_access = True
        subscription.status = SubscriptionStatus.PAST_DUE

        # Log the payment failure
        attempt_count = invoice_data.get("attempt_count", 0)
        self.logger.warning(
            f"Invoice payment failed for subscription {subscription_id} "
            f"(attempt {attempt_count}). Access paused."
        )

        # Warn if this is a final attempt (Stripe usually tries 4 times)
        if attempt_count >= 4:
            organization = await self._get_subscription_organization(subscription)
            if organization:
                self.logger.warning(
                    f"Multiple payment failures for subscription {subscription_id}. "
                    f"Organization {organization.id} will be downgraded to FREE if subscription is marked unpaid."
                )

        await self.db.commit()

    async def _handle_charge_refunded(self, charge_data: dict) -> None:
        """Handle charge refunds."""
        payment_intent_id = charge_data.get("payment_intent")
        if not payment_intent_id:
            return

        stmt = select(TopUp).where(TopUp.stripe_payment_intent_id == payment_intent_id)
        result = await self.db.execute(stmt)
        topup = result.scalar_one_or_none()

        if topup:
            # Reduce remaining credits proportionally
            refund_amount = charge_data.get("amount_refunded", 0)
            original_amount = charge_data.get("amount", 1)

            if original_amount > 0:
                refund_ratio = refund_amount / original_amount
                credits_to_remove = int(topup.credits_purchased * refund_ratio)

                # Remove from credit grants
                stmt = select(CreditGrant).where(CreditGrant.topup_id == topup.id)
                result = await self.db.execute(stmt)
                credit_grants = result.scalars().all()

                for grant in credit_grants:
                    grant.remaining_amount = max(
                        0, grant.remaining_amount - credits_to_remove
                    )
                    credits_to_remove = max(
                        0, credits_to_remove - grant.remaining_amount
                    )

                await self.db.commit()

    async def _find_or_create_subscription(
        self,
        organization_id: UUID,
        stripe_subscription_id: str,
        package_info: SubscriptionPackageConfig,
        subscription_data: dict,
    ) -> Subscription:
        """Find existing subscription or create/update with full billing details."""
        # Extract period fields from subscription items if not at root level
        current_period_start = subscription_data.get("current_period_start")
        current_period_end = subscription_data.get("current_period_end")

        if not current_period_start or not current_period_end:
            # Try to get from first subscription item
            items = subscription_data.get("items", {}).get("data", [])
            if items:
                first_item = items[0]
                current_period_start = first_item.get("current_period_start")
                current_period_end = first_item.get("current_period_end")

        # Check for required billing period fields
        if not current_period_start or not current_period_end:
            self.logger.warning(
                f"Subscription {stripe_subscription_id} missing period fields. "
                f"This is expected during checkout - waiting for subscription.created event."
            )
            # Return existing subscription if it exists, otherwise fail gracefully
            stmt = select(Subscription).where(
                Subscription.stripe_subscription_id == stripe_subscription_id
            )
            result = await self.db.execute(stmt)
            subscription = result.scalar_one_or_none()
            if subscription:
                return subscription
            # Can't create without period fields
            raise ValueError(
                f"Cannot create subscription {stripe_subscription_id} without period fields"
            )

        # Extract actual price from Stripe subscription items
        price_paid = 0.0
        items = subscription_data.get("items", {}).get("data", [])
        for item in items:
            price_data = item.get("price", {})
            usage_type = price_data.get("recurring", {}).get("usage_type")
            unit_amount = price_data.get("unit_amount", 0)
            # Skip metered/overage prices, only get base subscription price
            if usage_type != "metered":
                if unit_amount > 0:
                    price_paid = float(unit_amount) / 100.0
                    self.logger.info(
                        f"Extracted price_paid: {price_paid} from unit_amount: {unit_amount}"
                    )
                    break

        stmt = select(Subscription).where(
            Subscription.stripe_subscription_id == stripe_subscription_id
        )
        result = await self.db.execute(stmt)
        subscription = result.scalar_one_or_none()

        if subscription:
            # Update existing with full billing details
            subscription.status = (
                SubscriptionStatus.ACTIVE
                if subscription_data["status"] == "active"
                else SubscriptionStatus.INACTIVE
            )
            subscription.current_period_start = datetime.fromtimestamp(
                current_period_start, timezone.utc
            )
            subscription.current_period_end = datetime.fromtimestamp(
                current_period_end, timezone.utc
            )
            subscription.price_paid = price_paid
            self.logger.info(
                f"Updated subscription {stripe_subscription_id} with billing period "
                f"{subscription.current_period_start} to {subscription.current_period_end}"
            )
        else:
            # Create new with full details
            subscription = Subscription(
                id=uuid4(),
                organization_id=organization_id,
                stripe_subscription_id=stripe_subscription_id,
                stripe_customer_id=subscription_data["customer"],
                description=package_info.name,
                price_paid=price_paid,
                monthly_allowance=package_info.monthly_allowance,
                overage_unit_price=package_info.overage_unit_price,
                status=(
                    SubscriptionStatus.ACTIVE
                    if subscription_data["status"] == "active"
                    else SubscriptionStatus.INACTIVE
                ),
                overage_enabled=False,  # TODO: Get from organization settings
                current_period_start=datetime.fromtimestamp(
                    current_period_start, timezone.utc
                ),
                current_period_end=datetime.fromtimestamp(
                    current_period_end, timezone.utc
                ),
            )
            self.db.add(subscription)
            await self.db.commit()

        return subscription

    async def _create_usage_period(self, subscription: Subscription) -> None:
        """Create initial usage period and credit grant for subscription (idempotent)."""
        # Check for existing usage period to prevent duplicates
        period_stmt = select(UsagePeriod).where(
            UsagePeriod.subscription_id == subscription.id,
            UsagePeriod.period_start == subscription.current_period_start,
            UsagePeriod.period_end == subscription.current_period_end,
        )
        period_result = await self.db.execute(period_stmt)
        existing_period = period_result.scalar_one_or_none()

        if existing_period:
            self.logger.debug(
                f"Usage period already exists for subscription {subscription.id}"
            )
            return

        usage_period = UsagePeriod(
            id=uuid4(),
            subscription_id=subscription.id,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            overage_used=0,
            overage_reported=0,
            closed=False,
        )
        self.db.add(usage_period)

        # Create credit grant only if access is not paused
        if not subscription.pause_access:
            credit_grant = CreditGrant(
                id=uuid4(),
                organization_id=subscription.organization_id,
                subscription_id=subscription.id,
                grant_type=GrantType.SUBSCRIPTION,
                description=f"Monthly Subscription Credits - {subscription.current_period_start.strftime('%B %Y')}",
                amount=subscription.monthly_allowance,
                remaining_amount=subscription.monthly_allowance,
                expires_at=subscription.current_period_end,
            )
            self.db.add(credit_grant)
            self.logger.info(
                f"Created initial credit grant of {subscription.monthly_allowance} credits for subscription {subscription.id}"
            )
        else:
            self.logger.warning(
                f"Skipped initial credit grant creation for subscription {subscription.id} - access is paused due to payment issues"
            )

        self.logger.info(f"Created usage period for subscription {subscription.id}")

        await self.db.commit()

    async def _create_missed_credit_grants(self, subscription: Subscription) -> None:
        """Create credit grants that were missed while access was paused."""
        # Check if current period already has credit grants
        current_period_grants_stmt = select(CreditGrant).where(
            CreditGrant.subscription_id == subscription.id,
            CreditGrant.grant_type == GrantType.SUBSCRIPTION,
            CreditGrant.expires_at == subscription.current_period_end,
        )
        result = await self.db.execute(current_period_grants_stmt)
        existing_grants = result.scalars().all()

        if not existing_grants:
            # Create the missed credit grant for current period
            credit_grant = CreditGrant(
                id=uuid4(),
                organization_id=subscription.organization_id,
                subscription_id=subscription.id,
                grant_type=GrantType.SUBSCRIPTION,
                description=f"Restored Monthly Credits - {subscription.current_period_start.strftime('%B %Y')}",
                amount=subscription.monthly_allowance,
                remaining_amount=subscription.monthly_allowance,
                expires_at=subscription.current_period_end,
            )
            self.db.add(credit_grant)
            self.logger.info(
                f"Created missed credit grant of {subscription.monthly_allowance} credits for subscription {subscription.id} after payment restoration"
            )
        else:
            self.logger.debug(
                f"Credit grants already exist for current period of subscription {subscription.id}"
            )

    async def _get_organization_by_stripe_customer(
        self, customer_id: str
    ) -> Organization | None:
        """Get organization by Stripe customer ID."""
        # First try to find organization directly by customer ID
        stmt = select(Organization).where(
            Organization.stripe_customer_id == customer_id
        )
        result = await self.db.execute(stmt)
        organization = result.scalar_one_or_none()

        if organization:
            return organization

        # Fallback: Look up organization via existing subscription with this customer_id
        # This is for backward compatibility with existing data
        stmt = select(Subscription).where(
            Subscription.stripe_customer_id == customer_id
        )
        result = await self.db.execute(stmt)
        subscription = result.scalar_one_or_none()

        if subscription:
            # Get organization from subscription
            stmt = select(Organization).where(
                Organization.id == subscription.organization_id
            )
            result = await self.db.execute(stmt)
            organization = result.scalar_one_or_none()

            # If found, update the organization with the customer ID for future lookups
            if organization and not organization.stripe_customer_id:
                organization.stripe_customer_id = customer_id
                await self.db.commit()
                self.logger.info(
                    f"Updated organization {organization.id} with Stripe customer ID {customer_id}"
                )

            return organization

        # This is expected for new customers where subscription.created fires
        # before checkout.session.completed
        self.logger.debug(
            f"No existing organization found for Stripe customer {customer_id}. "
            "This is expected for new customers - will be processed via checkout.session.completed."
        )
        return None
