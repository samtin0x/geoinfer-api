"""Credits domain router."""

from fastapi import APIRouter, Request

from src.api.core.dependencies import AsyncSessionDep, CurrentUserAuthDep
from src.api.core.decorators.auth import require_permission
from src.database.models.organizations import OrganizationPermission
from src.api.core.messages import APIResponse, MessageCode, Paginated, PaginationInfo
from src.modules.billing.credits import CreditConsumptionService
from .schemas import (
    CreditGrantRecordModel,
    CreditUsageRecordModel,
)
from src.api.credits.schemas import (
    UsageHistoryResponse,
    CreditGrantsHistoryResponse,
    CreditsSummaryResponse,
)

router = APIRouter(
    prefix="/credits",
    tags=["credits"],
)


@router.get("/summary", response_model=CreditsSummaryResponse)
@require_permission(OrganizationPermission.VIEW_ANALYTICS)
async def get_credits_summary(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> CreditsSummaryResponse:
    """Get detailed credits summary including subscription, topups, and overage breakdown."""
    credit_service = CreditConsumptionService(db)
    summary_data = await credit_service.get_credits_summary(
        organization_id=current_user.organization.id
    )
    return APIResponse.success(message_code=MessageCode.SUCCESS, data=summary_data)


@router.get("/consumption", response_model=UsageHistoryResponse)
@require_permission(OrganizationPermission.VIEW_ANALYTICS)
async def get_credit_consumption_history(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
    limit: int = 50,
    offset: int = 0,
) -> UsageHistoryResponse:
    """Get credit consumption history - records of when credits were consumed/used."""
    credit_service = CreditConsumptionService(db)
    records_data_raw, total_records = await credit_service.get_usage_history(
        current_user.organization.id, limit, offset
    )
    records_data = [
        CreditUsageRecordModel(**record_dict) for record_dict in records_data_raw
    ]
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
    return APIResponse.success(message_code=MessageCode.SUCCESS, data=paginated_data)


@router.get("/grants", response_model=CreditGrantsHistoryResponse)
@require_permission(OrganizationPermission.VIEW_ANALYTICS)
async def get_credit_grants_history(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
    limit: int = 50,
    offset: int = 0,
) -> CreditGrantsHistoryResponse:
    """Get credit grants history - records of when credits were allocated/granted."""
    credit_service = CreditConsumptionService(db)
    grants_data_raw, total_grants = await credit_service.get_credit_grants_history(
        current_user.organization.id, limit, offset
    )
    grants_records = [
        CreditGrantRecordModel(**grant_dict) for grant_dict in grants_data_raw
    ]
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
    return APIResponse.success(message_code=MessageCode.SUCCESS, data=paginated_data)
