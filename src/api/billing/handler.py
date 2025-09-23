from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import APIResponse, MessageCode
from fastapi import status
from src.database.models import User, Subscription, TopUp
from .requests import BillingProductsResponse
from .models import (
    BillingProductsModel,
    SubscriptionProductModel,
    CreditPackageProductModel,
)


async def get_billing_products_handler(
    db: AsyncSession,
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> BillingProductsResponse:
    """Get user's billing products (subscriptions and credit packages)."""
    # Get user information
    user = await db.get(User, user_id)
    if not user or not user.organization_id:
        raise GeoInferException(MessageCode.USER_NOT_FOUND, status.HTTP_404_NOT_FOUND)

    organization_id = user.organization_id

    # Get paginated subscriptions
    subscriptions_stmt = (
        select(Subscription)
        .where(Subscription.organization_id == organization_id)
        .order_by(Subscription.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    subscriptions_result = await db.execute(subscriptions_stmt)
    subscriptions = subscriptions_result.scalars().all()

    # Get total subscriptions count
    total_subscriptions_stmt = select(func.count(Subscription.id)).where(
        Subscription.organization_id == organization_id
    )
    total_subscriptions_result = await db.execute(total_subscriptions_stmt)
    total_subscriptions = total_subscriptions_result.scalar() or 0

    # Get paginated topups
    topups_stmt = (
        select(TopUp)
        .where(TopUp.organization_id == organization_id)
        .order_by(TopUp.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    topups_result = await db.execute(topups_stmt)
    topups = topups_result.scalars().all()

    # Get total topups count
    total_topups_stmt = select(func.count(TopUp.id)).where(
        TopUp.organization_id == organization_id
    )
    total_topups_result = await db.execute(total_topups_stmt)
    total_topups = total_topups_result.scalar() or 0

    # Convert to response models
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

    billing_data = BillingProductsModel(
        subscriptions=subscription_models,
        credit_packages=topup_models,
        total_subscriptions=total_subscriptions,
        total_packages=total_topups,
    )

    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data=billing_data,
    )
