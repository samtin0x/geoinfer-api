"""Credits domain router."""

from fastapi import APIRouter, Request

from src.api.core.dependencies import AsyncSessionDep, CurrentUserAuthDep
from src.api.core.decorators.auth import require_permission
from src.database.models.organizations import OrganizationPermission
from .handler import (
    get_organization_credit_balance_handler,
    get_usage_history_handler,
    get_credit_grants_history_handler,
)
from .requests import (
    UserCreditBalanceResponse,
    UsageHistoryResponse,
    CreditGrantsHistoryResponse,
)

router = APIRouter(
    prefix="/credits",
    tags=["credits"],
)


@router.get("/balance", response_model=UserCreditBalanceResponse)
@require_permission(OrganizationPermission.VIEW_ANALYTICS)
async def get_credit_balance(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> UserCreditBalanceResponse:
    """Get current organization's credit balance and usage information."""

    return await get_organization_credit_balance_handler(
        db=db,
        organization_id=current_user.organization.id,
    )


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

    return await get_usage_history_handler(
        db=db,
        organization_id=current_user.organization.id,
        limit=limit,
        offset=offset,
    )


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

    return await get_credit_grants_history_handler(
        db=db,
        organization_id=current_user.organization.id,
        limit=limit,
        offset=offset,
    )
