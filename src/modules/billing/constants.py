"""Stripe pricing constants and configurations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from src.api.billing.schemas import (
    BillingCatalogModel,
    SubscriptionPlanModel,
    TopupPackageModel,
)
from src.database.models import PlanTier
from src.utils.settings.stripe import StripeSettings

_stripe_settings = StripeSettings()


class SubscriptionPackage(str, Enum):
    """Available subscription package types."""

    PRO_MONTHLY = "PRO_MONTHLY"
    PRO_YEARLY = "PRO_YEARLY"


class TopupPackage(str, Enum):
    """Available topup package types."""

    STARTER = "STARTER"
    GROWTH = "GROWTH"
    PRO = "PRO"


class StripeProductType(str, Enum):
    SUBSCRIPTION = "subscription"
    TOPUP_PACKAGE = "topup_package"


class UsageAlertLevel(str, Enum):
    """Alert levels for usage monitoring."""

    WARNING = "warning"
    EXCEEDED = "exceeded"


PRICE_PRO_MONTHLY_EUR = _stripe_settings.STRIPE_PRICE_PRO_MONTHLY_EUR
PRICE_PRO_YEARLY_EUR = _stripe_settings.STRIPE_PRICE_PRO_YEARLY_EUR
PRICE_PRO_OVERAGE_EUR = _stripe_settings.STRIPE_PRICE_PRO_OVERAGE_EUR
PRICE_TOPUP_STARTER_EUR = _stripe_settings.STRIPE_PRICE_TOPUP_STARTER_EUR
PRICE_TOPUP_GROWTH_EUR = _stripe_settings.STRIPE_PRICE_TOPUP_GROWTH_EUR
PRICE_TOPUP_PRO_EUR = _stripe_settings.STRIPE_PRICE_TOPUP_PRO_EUR

STRIPE_METER_EVENT_NAME = _stripe_settings.STRIPE_METER_EVENT_NAME

STRIPE_PORTAL_CONFIGURATION_ID = _stripe_settings.STRIPE_PORTAL_CONFIGURATION_ID
TOPUP_EXPIRY_DAYS = 90


# Mapping from Stripe price IDs to PlanTier (only subscription-related prices)
# Note: Topup prices are not included as they don't change plan tiers
PRICE_TO_PLAN_TIER: dict[str, PlanTier] = {
    PRICE_PRO_MONTHLY_EUR: PlanTier.SUBSCRIBED,
    PRICE_PRO_YEARLY_EUR: PlanTier.SUBSCRIBED,
    PRICE_PRO_OVERAGE_EUR: PlanTier.SUBSCRIBED,
}

# Mapping from PlanTier to SubscriptionPackage for pricing lookup
PLANTIER_TO_PACKAGE: dict[PlanTier, SubscriptionPackage] = {
    PlanTier.SUBSCRIBED: SubscriptionPackage.PRO_MONTHLY,
    PlanTier.SUBSCRIBED: SubscriptionPackage.PRO_YEARLY,
}


@dataclass(frozen=True)
class SubscriptionPackageConfig:
    """Configuration for a subscription package."""

    base_price_id: str
    overage_price_id: str
    monthly_allowance: int
    overage_unit_price: Decimal
    name: str
    price_monthly: Decimal | None = None
    price_yearly: Decimal | None = None


@dataclass(frozen=True)
class TopupPackageConfig:
    """Configuration for a topup package."""

    price_id: str
    credits: int
    price: Decimal
    name: str
    description: str
    expiry_days: int


# Base configuration for subscription packages
SUBSCRIPTION_PACKAGES: dict[SubscriptionPackage, SubscriptionPackageConfig] = {
    SubscriptionPackage.PRO_MONTHLY: SubscriptionPackageConfig(
        base_price_id=PRICE_PRO_MONTHLY_EUR,
        overage_price_id=PRICE_PRO_OVERAGE_EUR,
        monthly_allowance=1000,
        overage_unit_price=Decimal("0.060"),
        price_monthly=Decimal("60.00"),
        name="Monthly Subscription",
    ),
    SubscriptionPackage.PRO_YEARLY: SubscriptionPackageConfig(
        base_price_id=PRICE_PRO_YEARLY_EUR,
        overage_price_id=PRICE_PRO_OVERAGE_EUR,
        monthly_allowance=1000,
        overage_unit_price=Decimal("0.060"),
        price_yearly=Decimal("600.00"),
        name="Yearly Subscription",
    ),
}

# Base configuration for topup packages
TOPUP_PACKAGES: dict[TopupPackage, TopupPackageConfig] = {
    TopupPackage.STARTER: TopupPackageConfig(
        price_id=PRICE_TOPUP_STARTER_EUR,
        credits=200,
        price=Decimal("15.00"),
        name="Starter Wallet",
        description="200 credits",
        expiry_days=TOPUP_EXPIRY_DAYS,
    ),
    TopupPackage.GROWTH: TopupPackageConfig(
        price_id=PRICE_TOPUP_GROWTH_EUR,
        credits=700,
        price=Decimal("49.00"),
        name="Growth Topup",
        description="700 credits",
        expiry_days=TOPUP_EXPIRY_DAYS,
    ),
    TopupPackage.PRO: TopupPackageConfig(
        price_id=PRICE_TOPUP_PRO_EUR,
        credits=1600,
        price=Decimal("100.00"),
        name="Pro Topup",
        description="1600 credits",
        expiry_days=TOPUP_EXPIRY_DAYS,
    ),
}


def should_alert(
    usage_percentage: float, organization_alert_percentages: list[float]
) -> list[float]:
    """Check which alert thresholds should be triggered and return the percentages."""
    triggered_percentages: list[float] = []

    if not organization_alert_percentages:
        return triggered_percentages

    for percentage in organization_alert_percentages:
        if usage_percentage >= percentage:
            triggered_percentages.append(percentage)

    return triggered_percentages


def get_all_packages() -> BillingCatalogModel:
    """Get all package configurations for API responses."""
    return BillingCatalogModel(
        currency="EUR",
        subscriptionPackages={
            package.value: SubscriptionPlanModel(
                base_price_id=config.base_price_id,
                overage_price_id=config.overage_price_id,
                monthly_allowance=config.monthly_allowance,
                overage_unit_price=float(config.overage_unit_price),
                price_monthly=(
                    float(config.price_monthly) if config.price_monthly else None
                ),
                price_yearly=(
                    float(config.price_yearly) if config.price_yearly else None
                ),
                name=config.name,
            )
            for package, config in SUBSCRIPTION_PACKAGES.items()
        },
        topupPackages={
            package.value: TopupPackageModel(
                price_id=config.price_id,
                credits=config.credits,
                price=float(config.price),
                name=config.name,
                description=config.description,
                expiry_days=config.expiry_days,
            )
            for package, config in TOPUP_PACKAGES.items()
        },
    )
