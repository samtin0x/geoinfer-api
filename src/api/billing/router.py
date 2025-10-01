from uuid import UUID

from fastapi import APIRouter, Request, Query, Path, status

from src.api.core.dependencies import AsyncSessionDep, CurrentUserAuthDep
from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.api.core.decorators.auth import require_permission, require_plan_tier
from src.api.core.decorators.rate_limit import rate_limit
from src.api.core.messages import APIResponse, Paginated, PaginationInfo
from src.database.models.organizations import PlanTier, OrganizationPermission
from src.modules.billing.constants import get_all_packages
from src.modules.billing.use_cases import BillingQueryService
from src.api.billing.schemas import (
    BillingProductsModel,
    BillingCatalogModel,
    OverageSettingsModel,
    OverageSettingsResponseModel,
    SubscriptionProductModel,
    CreditPackageProductModel,
    AlertSettingsModel,
    AlertSettingsUpdateModel,
    UsageAlertModel,
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    PortalSessionRequest,
    PortalSessionResponse,
)

router = APIRouter(
    prefix="/billing",
    tags=["billing"],
)


@router.get("/products", response_model=APIResponse[BillingProductsModel])
@require_permission(OrganizationPermission.MANAGE_BILLING)
async def get_billing_products(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> APIResponse[BillingProductsModel]:
    """Get all billing products (subscriptions and topups) for the organization."""
    org_id = current_user.organization.id
    billing_service = BillingQueryService(db)
    subscriptions, total_subscriptions = await billing_service.fetch_subscriptions(
        org_id, limit, offset
    )
    topups, total_topups = await billing_service.fetch_topups(org_id, limit, offset)

    # Use model_validate to convert ORM objects directly
    subscription_models = [
        SubscriptionProductModel.model_validate(sub) for sub in subscriptions
    ]

    topup_models = [CreditPackageProductModel.model_validate(topup) for topup in topups]

    payload = BillingProductsModel(
        subscriptions=subscription_models,
        credit_packages=topup_models,
        total_subscriptions=total_subscriptions,
        total_packages=total_topups,
    )
    return APIResponse.success(data=payload)


@router.get("/catalog", response_model=APIResponse[BillingCatalogModel])
async def get_billing_catalog() -> APIResponse[BillingCatalogModel]:
    catalog = get_all_packages()
    return APIResponse.success(data=catalog)


@router.get("/alerts/history", response_model=APIResponse[Paginated[UsageAlertModel]])
@require_permission(OrganizationPermission.MANAGE_BILLING)
@require_plan_tier([PlanTier.SUBSCRIBED])
async def check_usage_alerts(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> APIResponse[Paginated[UsageAlertModel]]:
    """Check for usage alerts across all active subscriptions."""
    org_id = current_user.organization.id
    billing_service = BillingQueryService(db)
    alerts, total = await billing_service.check_usage_alerts(org_id, limit, offset)

    alert_models = [UsageAlertModel(**alert) for alert in alerts]

    pagination = PaginationInfo(
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + limit < total,
    )

    return APIResponse.success(
        data=Paginated(items=alert_models, pagination=pagination)
    )


@router.patch(
    "/subscriptions/{subscription_id}/overage-settings",
    response_model=APIResponse[OverageSettingsResponseModel],
)
@require_permission(OrganizationPermission.MANAGE_BILLING)
async def update_overage_settings(
    request: Request,
    overage_settings: OverageSettingsModel,
    subscription_id: UUID = Path(..., description="Subscription ID"),
    db: AsyncSessionDep = None,
    current_user: CurrentUserAuthDep = None,
) -> APIResponse[OverageSettingsResponseModel]:
    billing_service = BillingQueryService(db)
    subscription = await billing_service.update_overage_settings(
        subscription_id,
        current_user.organization.id,
        overage_settings.enabled,
        overage_settings.userExtraCap,
    )

    return APIResponse.success(
        data=OverageSettingsResponseModel(
            subscription_id=subscription.id,
            overage_enabled=subscription.overage_enabled,
            user_extra_cap=subscription.user_extra_cap,
        )
    )


@router.get(
    "/subscriptions/{subscription_id}/alert-settings",
    response_model=APIResponse[AlertSettingsModel],
)
@require_permission(OrganizationPermission.MANAGE_BILLING)
@require_plan_tier([PlanTier.SUBSCRIBED])
async def get_alert_settings(
    request: Request,
    subscription_id: UUID = Path(..., description="Subscription ID"),
    db: AsyncSessionDep = None,
    current_user: CurrentUserAuthDep = None,
) -> APIResponse[AlertSettingsModel]:
    billing_service = BillingQueryService(db)
    await billing_service.get_subscription(
        subscription_id, current_user.organization.id
    )

    alert_settings = await billing_service.get_alert_settings(subscription_id)

    return APIResponse.success(data=AlertSettingsModel.model_validate(alert_settings))


@router.patch(
    "/subscriptions/{subscription_id}/alert-settings",
    response_model=APIResponse[AlertSettingsModel],
)
@require_permission(OrganizationPermission.MANAGE_BILLING)
@require_plan_tier([PlanTier.SUBSCRIBED])
async def update_alert_settings(
    request: Request,
    alert_settings_update: AlertSettingsUpdateModel,
    subscription_id: UUID = Path(..., description="Subscription ID"),
    db: AsyncSessionDep = None,
    current_user: CurrentUserAuthDep = None,
) -> APIResponse[AlertSettingsModel]:
    billing_service = BillingQueryService(db)
    await billing_service.get_subscription(
        subscription_id, current_user.organization.id
    )

    alert_settings = await billing_service.update_alert_settings(
        subscription_id,
        alert_settings_update.alert_thresholds,
        alert_settings_update.alert_destinations,
        alert_settings_update.alerts_enabled,
        alert_settings_update.locale,
    )

    return APIResponse.success(data=AlertSettingsModel.model_validate(alert_settings))


@router.post(
    "/subscriptions/{subscription_id}/test-alert", response_model=APIResponse[bool]
)
@require_permission(OrganizationPermission.MANAGE_BILLING)
@require_plan_tier([PlanTier.SUBSCRIBED])
@rate_limit(limit=3, window_seconds=86400)
async def test_alert_email(
    request: Request,
    subscription_id: UUID = Path(..., description="Subscription ID"),
    locale: str = "en",
    db: AsyncSessionDep = None,
    current_user: CurrentUserAuthDep = None,
) -> APIResponse[bool]:
    billing_service = BillingQueryService(db)
    result = await billing_service.send_test_alert(
        subscription_id, current_user.organization.id, locale
    )

    return APIResponse.success(data=result)


@router.post(
    "/stripe/checkout-session", response_model=APIResponse[CheckoutSessionResponse]
)
@require_permission(OrganizationPermission.MANAGE_BILLING)
async def create_checkout_session(
    request: Request,
    request_data: CheckoutSessionRequest,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> APIResponse[CheckoutSessionResponse]:
    """Create a Stripe checkout session for subscription or topup purchase."""
    from src.modules.billing.stripe.service import StripePaymentService
    from src.modules.billing.constants import StripeProductType

    stripe_service = StripePaymentService(db)

    # Ensure organization has a Stripe customer
    if not current_user.organization.stripe_customer_id:
        raise GeoInferException(
            MessageCode.BAD_REQUEST,
            status.HTTP_400_BAD_REQUEST,
            details={
                "description": "Organization does not have a Stripe customer. Please contact support."
            },
        )

    product_type = StripeProductType(request_data.product_type)

    checkout_session = await stripe_service.create_checkout_session(
        customer_id=current_user.organization.stripe_customer_id,
        price_id=request_data.price_id,
        success_url=request_data.success_url,
        cancel_url=request_data.cancel_url,
        organization_id=current_user.organization.id,
        product_type=product_type,
    )

    response_data = CheckoutSessionResponse(
        session_id=checkout_session.id, url=checkout_session.url
    )

    return APIResponse.success(data=response_data)


@router.post(
    "/stripe/portal-session", response_model=APIResponse[PortalSessionResponse]
)
@require_permission(OrganizationPermission.MANAGE_BILLING)
async def create_portal_session(
    request: Request,
    request_data: PortalSessionRequest,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> APIResponse[PortalSessionResponse]:
    """Create a Stripe customer portal session for managing billing."""
    from src.modules.billing.stripe.service import StripePaymentService
    from src.api.core.exceptions.base import GeoInferException
    from src.api.core.messages import MessageCode
    from fastapi import status

    stripe_service = StripePaymentService(db)

    # Check if organization has a Stripe customer ID
    if not current_user.organization.stripe_customer_id:
        raise GeoInferException(
            MessageCode.BAD_REQUEST,
            status.HTTP_400_BAD_REQUEST,
            details={
                "description": "No Stripe customer found for this organization. Please make a purchase first."
            },
        )

    portal_session = await stripe_service.create_customer_portal_session(
        customer_id=current_user.organization.stripe_customer_id,
        return_url=request_data.return_url,
    )

    return APIResponse.success(data=PortalSessionResponse(url=portal_session.url))
