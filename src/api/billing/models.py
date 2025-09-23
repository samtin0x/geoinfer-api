"""Billing response models."""

from __future__ import annotations

from pydantic import BaseModel


class SubscriptionProductModel(BaseModel):
    """Subscription product information."""

    id: str
    description: str
    price_paid: float
    monthly_allowance: int
    status: str
    current_period_start: str
    current_period_end: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class CreditPackageProductModel(BaseModel):
    """Credit package product information."""

    id: str
    description: str
    price_paid: float
    credits_purchased: int
    package_type: str
    expires_at: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class BillingProductsModel(BaseModel):
    """Billing products (subscriptions and credit packages)."""

    subscriptions: list[SubscriptionProductModel]
    credit_packages: list[CreditPackageProductModel]
    total_subscriptions: int
    total_packages: int

    model_config = {"from_attributes": True}
