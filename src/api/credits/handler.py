"""Credits domain handlers."""

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.core.messages import APIResponse, MessageCode, Paginated, PaginationInfo
from src.services.prediction.credits import PredictionCreditService
from .requests import (
    UserCreditBalanceResponse,
    UsageHistoryResponse,
    CreditGrantsHistoryResponse,
)
from .models import (
    UserCreditBalanceModel,
    CreditGrantRecordModel,
    CreditUsageRecordModel,
)


async def get_organization_credit_balance_handler(
    db: AsyncSession,
    organization_id: UUID,
) -> UserCreditBalanceResponse:
    """Get organization's current available credit balance."""
    credit_service = PredictionCreditService(db)

    subscription_credits, top_up_credits = (
        await credit_service.get_organization_credits(organization_id=organization_id)
    )

    balance_dict = {
        "total_credits": subscription_credits + top_up_credits,
        "subscription_credits": subscription_credits,
        "top_up_credits": top_up_credits,
    }

    balance_data = UserCreditBalanceModel(**balance_dict)

    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data=balance_data,
    )


async def get_usage_history_handler(
    db: AsyncSession,
    organization_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> UsageHistoryResponse:
    """Get organization's credit consumption history from usage_records table."""
    credit_service = PredictionCreditService(db)

    # Get data from service
    records_data_raw, total_records = await credit_service.get_usage_history(
        organization_id, limit, offset
    )

    # Convert to pydantic models
    records_data = [
        CreditUsageRecordModel(**record_dict) for record_dict in records_data_raw
    ]

    # Create paginated response
    pagination_info = PaginationInfo(
        total=total_records,
        limit=limit,
        offset=offset,
        has_more=offset + len(records_data) < total_records,
    )

    paginated_data = Paginated[CreditUsageRecordModel](
        items=records_data,
        pagination=pagination_info,
    )

    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data=paginated_data,
    )


async def get_credit_grants_history_handler(
    db: AsyncSession,
    organization_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> CreditGrantsHistoryResponse:
    """Get organization's credit grants history with pagination."""
    credit_service = PredictionCreditService(db)

    # Get data from service
    grants_data_raw, total_grants = await credit_service.get_credit_grants_history(
        organization_id, limit, offset
    )

    # Convert to pydantic models
    grants_records = [
        CreditGrantRecordModel(**grant_dict) for grant_dict in grants_data_raw
    ]

    # Create paginated response
    pagination_info = PaginationInfo(
        total=total_grants,
        limit=limit,
        offset=offset,
        has_more=offset + len(grants_records) < total_grants,
    )

    paginated_data = Paginated[CreditGrantRecordModel](
        items=grants_records,
        pagination=pagination_info,
    )

    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data=paginated_data,
    )
