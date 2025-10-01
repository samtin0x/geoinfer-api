"""Billing API schemas (combined requests/models)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID
import re

from pydantic import BaseModel, field_validator

from src.api.core.messages import APIResponse


class SubscriptionProductModel(BaseModel):
    id: UUID
    description: str
    price_paid: float
    monthly_allowance: int
    status: str
    overage_enabled: bool
    user_extra_cap: int | None
    pause_access: bool
    cancel_at_period_end: bool
    current_period_start: datetime
    current_period_end: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CreditPackageProductModel(BaseModel):
    id: UUID
    description: str
    price_paid: float
    credits_purchased: int
    package_type: str
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BillingProductsModel(BaseModel):
    subscriptions: list[SubscriptionProductModel]
    credit_packages: list[CreditPackageProductModel]
    total_subscriptions: int
    total_packages: int

    class Config:
        from_attributes = True


# New billing catalog schemas
class AlertConfigModel(BaseModel):
    email_addresses: list[str]
    alert_percentages: list[float]
    enabled: bool


class OverageConfigModel(BaseModel):
    max_amount: int | None
    unit_price: float
    enabled: bool
    block_on_cap: bool


class SubscriptionPlanModel(BaseModel):
    base_price_id: str
    overage_price_id: str
    monthly_allowance: int
    overage_unit_price: float
    price_monthly: float | None
    price_yearly: float | None
    name: str


class TopupPackageModel(BaseModel):
    price_id: str
    credits: int
    price: float
    name: str
    description: str
    expiry_days: int


class BillingCatalogModel(BaseModel):
    currency: str
    subscriptionPackages: dict[str, SubscriptionPlanModel]
    topupPackages: dict[str, TopupPackageModel]


class OverageSettingsModel(BaseModel):
    enabled: bool
    userExtraCap: int | None = 0  # 0 means no overage allowed, None means unlimited


class OverageSettingsResponseModel(BaseModel):
    subscription_id: UUID
    overage_enabled: bool
    user_extra_cap: int | None  # None means unlimited overage

    class Config:
        from_attributes = True


class OrganizationUsageModel(BaseModel):
    """Aggregated usage information for an organization across all products."""

    total_remaining_monthly: int
    total_remaining_topups: int
    total_overage_used: int
    active_subscriptions: int
    active_topups: int

    class Config:
        from_attributes = True


class AlertSettingsModel(BaseModel):
    subscription_id: UUID
    alert_thresholds: list[float]
    alert_destinations: list[str]
    alerts_enabled: bool
    locale: str

    class Config:
        from_attributes = True


class AlertSettingsUpdateModel(BaseModel):
    alert_thresholds: list[float] | None = None
    alert_destinations: list[str] | None = None
    alerts_enabled: bool | None = None
    locale: str | None = None

    @field_validator("alert_thresholds")
    @classmethod
    def validate_alert_thresholds(cls, v):
        if v is None:
            return v

        if not isinstance(v, list):
            raise ValueError("alert_thresholds must be a list")

        # Allow empty thresholds when alerts are disabled
        if len(v) == 0:
            return v

        # Check each threshold is between 0 and 1
        for threshold in v:
            if not isinstance(threshold, (int, float)):
                raise ValueError(
                    f"all alert_thresholds must be numbers, got {type(threshold)}"
                )
            if not (0 <= threshold <= 1):
                raise ValueError(
                    f"all alert_thresholds must be between 0 and 1, got {threshold}"
                )

        # Check if sorted in ascending order
        if sorted(v) != v:
            raise ValueError("alert_thresholds must be sorted in ascending order")

        return v

    @field_validator("alert_destinations")
    @classmethod
    def validate_alert_destinations(cls, v):
        if v is None:
            return v

        if not isinstance(v, list):
            raise ValueError("alert_destinations must be a list")

        # Basic email validation regex
        email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

        for email in v:
            if not isinstance(email, str):
                raise ValueError(
                    f"all alert_destinations must be strings, got {type(email)}"
                )
            if not email_pattern.match(email):
                raise ValueError(f"invalid email format: {email}")

        return v

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, v):
        if v is None:
            return v

        if not isinstance(v, str):
            raise ValueError("locale must be a string")

        locale_pattern = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")
        if not locale_pattern.match(v):
            raise ValueError(
                f'invalid locale format: {v}. Expected format: "en" or "en-US"'
            )

        return v


class UsageAlertModel(BaseModel):
    subscription_id: str
    subscription_name: str
    usage_percentage: float
    alert_message: str
    alert_type: str
    monthly_allowance: int
    current_usage: int
    new_alert: bool
    alert_destinations: list[str]  # Recipients

    class Config:
        from_attributes = True


class CheckoutSessionRequest(BaseModel):
    price_id: str
    success_url: str
    cancel_url: str
    product_type: str = "subscription"


class CheckoutSessionResponse(BaseModel):
    session_id: str
    url: str


class PortalSessionRequest(BaseModel):
    return_url: str


class PortalSessionResponse(BaseModel):
    url: str


# Response type aliases (kept for backwards compatibility, but prefer explicit APIResponse[T])
BillingProductsResponse = APIResponse[BillingProductsModel]
BillingCatalogResponse = APIResponse[BillingCatalogModel]
OrganizationUsageResponse = APIResponse[OrganizationUsageModel]
AlertSettingsResponse = APIResponse[AlertSettingsModel]
OverageSettingsResponse = APIResponse[AlertSettingsModel]
TestAlertResponse = APIResponse[bool]
