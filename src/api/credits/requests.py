"""Credits domain requests and responses."""

from src.api.core.messages import APIResponse, Paginated
from .models import (
    UserCreditBalanceModel,
    CreditGrantRecordModel,
    CreditUsageRecordModel,
)


# Response Models
UserCreditBalanceResponse = APIResponse[UserCreditBalanceModel]
UsageHistoryResponse = APIResponse[Paginated[CreditUsageRecordModel]]
CreditGrantsHistoryResponse = APIResponse[Paginated[CreditGrantRecordModel]]
