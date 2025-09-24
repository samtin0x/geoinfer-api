"""Billing API schemas (combined requests/models)."""

from __future__ import annotations

from pydantic import BaseModel
from src.api.core.messages import APIResponse


class SubscriptionProductModel(BaseModel):
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
    subscriptions: list[SubscriptionProductModel]
    credit_packages: list[CreditPackageProductModel]
    total_subscriptions: int
    total_packages: int

    model_config = {"from_attributes": True}


BillingProductsResponse = APIResponse[BillingProductsModel]
