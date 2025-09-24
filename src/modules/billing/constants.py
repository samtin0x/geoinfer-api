"""Stripe pricing constants and configurations."""

from decimal import Decimal
from enum import Enum

from src.database.models import PlanTier


class StripeProductType(str, Enum):
    SUBSCRIPTION = "subscription"
    CREDIT_PACKAGE = "credit_package"


STRIPE_PRICE_MAP = {
    PlanTier.SUBSCRIBED: {
        "monthly": "price_enterprise_monthly_id",
        "yearly": "price_enterprise_yearly_id",
        "credits": -1,
        "price_monthly": Decimal("99.99"),
        "price_yearly": Decimal("999.99"),
    },
}

CREDIT_PACKAGES = {
    "small": {
        "price_id": "price_credits_small_id",
        "credits": 100,
        "price": Decimal("9.99"),
        "name": "Small Credit Package",
    },
    "medium": {
        "price_id": "price_credits_medium_id",
        "credits": 500,
        "price": Decimal("39.99"),
        "name": "Medium Credit Package",
    },
    "large": {
        "price_id": "price_credits_large_id",
        "credits": 1000,
        "price": Decimal("69.99"),
        "name": "Large Credit Package",
    },
    "enterprise": {
        "price_id": "price_credits_enterprise_id",
        "credits": 5000,
        "price": Decimal("299.99"),
        "name": "Enterprise Credit Package",
    },
}
