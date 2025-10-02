"""Credits API schemas (combined models/requests)."""

from datetime import datetime
from pydantic import BaseModel
from src.api.core.messages import APIResponse, Paginated


class CreditUsageRecordModel(BaseModel):
    id: str
    organization_id: str
    credits_consumed: int
    api_key_id: str | None
    subscription_id: str | None
    topup_id: str | None
    description: str | None
    created_at: str

    model_config = {"from_attributes": True}


class CreditGrantRecordModel(BaseModel):
    id: str
    grant_type: str
    description: str
    amount: int
    remaining_amount: int
    expires_at: str | None
    subscription_id: str | None
    topup_id: str | None
    created_at: str

    model_config = {"from_attributes": True}


class SubscriptionCreditsSummaryModel(BaseModel):
    id: str
    monthly_allowance: int
    granted_this_period: int
    used_this_period: int
    remaining: int
    period_start: datetime
    period_end: datetime
    status: str
    billing_interval: str  # "monthly" or "yearly"
    price_paid: float
    overage_unit_price: float
    cancel_at_period_end: bool
    pause_access: bool


class OverageSummaryModel(BaseModel):
    enabled: bool
    used: int
    reported_to_stripe: int
    cap: int | None
    remaining_until_cap: int | None
    unit_price: float


class TopupCreditSummaryModel(BaseModel):
    id: str
    name: str
    granted: int
    used: int
    remaining: int
    expires_at: datetime | None
    purchased_at: datetime


class CreditsSummaryTotalsModel(BaseModel):
    total_available: int
    subscription_credits: int
    topup_credits: int
    overage_credits: int


class CreditsSummaryModel(BaseModel):
    subscription: SubscriptionCreditsSummaryModel | None
    overage: OverageSummaryModel | None
    topups: list[TopupCreditSummaryModel]
    summary: CreditsSummaryTotalsModel


# Response type aliases
UsageHistoryResponse = APIResponse[Paginated[CreditUsageRecordModel]]
CreditGrantsHistoryResponse = APIResponse[Paginated[CreditGrantRecordModel]]
CreditsSummaryResponse = APIResponse[CreditsSummaryModel]
