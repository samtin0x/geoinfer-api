from fastapi import APIRouter, Request, Query

from src.api.core.dependencies import AsyncSessionDep, CurrentUserAuthDep
from src.api.core.decorators.auth import require_permission
from src.database.models.organizations import OrganizationPermission
from src.api.core.messages import APIResponse
from src.api.billing.schemas import (
    BillingProductsModel,
    BillingProductsResponse,
    SubscriptionProductModel,
    CreditPackageProductModel,
)
from src.modules.billing.use_cases import BillingQueryService

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
    org_id = current_user.organization.id
    billing_query = BillingQueryService(db)
    subscriptions, total_subscriptions = await billing_query.fetch_subscriptions(
        org_id, limit, offset
    )
    topups, total_topups = await billing_query.fetch_topups(org_id, limit, offset)

    subscription_models = [
        SubscriptionProductModel(
            id=str(sub.id),
            description=sub.description,
            price_paid=sub.price_paid,
            monthly_allowance=sub.monthly_allowance,
            status=sub.status,
            current_period_start=sub.current_period_start.isoformat(),
            current_period_end=sub.current_period_end.isoformat(),
            created_at=sub.created_at.isoformat(),
            updated_at=sub.updated_at.isoformat(),
        )
        for sub in subscriptions
    ]

    topup_models = [
        CreditPackageProductModel(
            id=str(topup.id),
            description=topup.description,
            price_paid=topup.price_paid,
            credits_purchased=topup.credits_purchased,
            package_type=topup.package_type,
            expires_at=topup.expires_at.isoformat() if topup.expires_at else None,
            created_at=topup.created_at.isoformat(),
            updated_at=topup.updated_at.isoformat(),
        )
        for topup in topups
    ]

    payload = BillingProductsModel(
        subscriptions=subscription_models,
        credit_packages=topup_models,
        total_subscriptions=total_subscriptions,
        total_packages=total_topups,
    )
    return APIResponse.success(data=payload)
