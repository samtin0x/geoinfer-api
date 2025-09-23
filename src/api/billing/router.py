from fastapi import APIRouter, Request, Query

from src.api.core.dependencies import AsyncSessionDep, CurrentUserAuthDep
from src.api.core.decorators.auth import require_permission
from src.database.models.organizations import OrganizationPermission
from .handler import get_billing_products_handler
from .requests import BillingProductsResponse

router = APIRouter(
    prefix="/billing",
    tags=["billing"],
)


@router.get("/products", response_model=BillingProductsResponse)
@require_permission(OrganizationPermission.MANAGE_BILLING)
async def get_billing_products(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> BillingProductsResponse:

    return await get_billing_products_handler(
        db=db,
        user_id=current_user.user.id,
        limit=limit,
        offset=offset,
    )
