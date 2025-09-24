"""Credits API schemas (combined models/requests)."""

from pydantic import BaseModel
from src.api.core.messages import APIResponse, Paginated


class UserCreditBalanceModel(BaseModel):
    total_credits: int = 0
    subscription_credits: int = 0
    top_up_credits: int = 0

    model_config = {"from_attributes": True}


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


UserCreditBalanceResponse = APIResponse[UserCreditBalanceModel]
UsageHistoryResponse = APIResponse[Paginated[CreditUsageRecordModel]]
CreditGrantsHistoryResponse = APIResponse[Paginated[CreditGrantRecordModel]]
