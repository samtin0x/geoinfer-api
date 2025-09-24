"""Analytics API router."""

from fastapi import APIRouter, Request, Query

from .models import GroupByType

from src.api.core.dependencies import (
    AsyncSessionDep,
    CurrentUserAuthDep,
    AnalyticsServiceDep,
)
from src.api.core.decorators.auth import require_permission
from src.database.models.organizations import OrganizationPermission
from .models import (
    UsageTimeseries,
    UserUsagePaginated,
    OrganizationAnalytics,
    APIKeyUsage,
)
from src.api.core.messages import APIResponse

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/timeseries", response_model=APIResponse[list[UsageTimeseries]])
@require_permission(OrganizationPermission.VIEW_ANALYTICS)
async def get_usage_timeseries(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
    analytics_service: AnalyticsServiceDep,
    days: int = Query(default=30, ge=1, le=365),
    group_by: GroupByType = Query(default=GroupByType.DAY),
) -> APIResponse[list[UsageTimeseries]]:
    """Get usage timeseries data for the current user's organization."""
    organization_id = current_user.organization.id
    data = await analytics_service.get_usage_timeseries(
        organization_id=organization_id, days=days, group_by=group_by
    )
    timeseries_data = [UsageTimeseries(**item) for item in data]
    return APIResponse.success(
        data=timeseries_data,
    )


@router.get("/users", response_model=APIResponse[UserUsagePaginated])
@require_permission(OrganizationPermission.VIEW_ANALYTICS)
async def get_user_usage_analytics(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
    analytics_service: AnalyticsServiceDep,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> APIResponse[UserUsagePaginated]:
    """Get user usage analytics for the current user's organization with pagination."""
    organization_id = current_user.organization.id

    paginated_data = await analytics_service.get_organization_user_usage(
        organization_id=organization_id, days=days, limit=limit, offset=offset
    )

    return APIResponse.success(
        data=paginated_data,
    )


@router.get("/organization", response_model=APIResponse[OrganizationAnalytics])
@require_permission(OrganizationPermission.VIEW_ANALYTICS)
async def get_organization_analytics(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
    analytics_service: AnalyticsServiceDep,
) -> APIResponse[OrganizationAnalytics]:
    """Get detailed analytics for the current user's organization."""
    organization_id = current_user.organization.id
    data = await analytics_service.get_organization_analytics(organization_id)
    analytics_data = OrganizationAnalytics(**data)
    return APIResponse.success(
        data=analytics_data,
    )


@router.get("/api-keys", response_model=APIResponse[list[APIKeyUsage]])
@require_permission(OrganizationPermission.VIEW_ANALYTICS)
async def get_api_key_usage_analytics(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
    analytics_service: AnalyticsServiceDep,
    limit: int = Query(default=20, ge=1, le=100),
    days: int = Query(default=30, ge=1, le=365),
) -> APIResponse[list[APIKeyUsage]]:
    """Get analytics for API key usage for the current user's organization."""
    organization_id = current_user.organization.id
    data = await analytics_service.get_api_key_usage_analytics(
        organization_id=organization_id, limit=limit, days=days
    )
    api_key_usage_data = [APIKeyUsage(**item) for item in data]
    return APIResponse.success(
        data=api_key_usage_data,
    )
