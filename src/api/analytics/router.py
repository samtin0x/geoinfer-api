"""Analytics API router."""

from fastapi import APIRouter, Request, Query

from .models import GroupByType

from src.api.core.dependencies import (
    CurrentUserAuthDep,
    AnalyticsServiceDep,
)
from src.api.core.decorators.auth import require_permission
from src.api.core.messages import MessageCode
from src.database.models.organizations import OrganizationPermission
from .models import (
    UsageTimeseries,
    OrganizationAnalytics,
    APIKeyUsage,
)
from .requests import (
    UsageTimeseriesResponse,
    OrganizationUserUsageResponse,
    OrganizationAnalyticsResponse,
    APIKeyUsageResponse,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/timeseries", response_model=UsageTimeseriesResponse)
@require_permission(OrganizationPermission.VIEW_ANALYTICS)
async def get_usage_timeseries(
    current_user: CurrentUserAuthDep,
    request: Request,
    analytics_service: AnalyticsServiceDep,
    days: int = Query(default=30, ge=1, le=365),
    group_by: GroupByType = Query(default=GroupByType.DAY),
) -> UsageTimeseriesResponse:
    """Get usage timeseries data for the current user's organization."""
    organization_id = current_user.organization.id
    data = await analytics_service.get_usage_timeseries(
        organization_id=organization_id, days=days, group_by=group_by
    )
    timeseries_data = [UsageTimeseries(**item) for item in data]
    return UsageTimeseriesResponse(
        message_code=MessageCode.SUCCESS,
        message="Success",
        data=timeseries_data,
    )


@router.get("/users", response_model=OrganizationUserUsageResponse)
@require_permission(OrganizationPermission.VIEW_ANALYTICS)
async def get_user_usage_analytics(
    current_user: CurrentUserAuthDep,
    analytics_service: AnalyticsServiceDep,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> OrganizationUserUsageResponse:
    """Get user usage analytics for the current user's organization with pagination."""
    organization_id = current_user.organization.id

    paginated_data = await analytics_service.get_organization_user_usage(
        organization_id=organization_id, days=days, limit=limit, offset=offset
    )

    return OrganizationUserUsageResponse(
        message_code=MessageCode.SUCCESS,
        message="Success",
        data=paginated_data,
    )


@router.get("/organization", response_model=OrganizationAnalyticsResponse)
@require_permission(OrganizationPermission.VIEW_ANALYTICS)
async def get_organization_analytics(
    current_user: CurrentUserAuthDep,
    analytics_service: AnalyticsServiceDep,
) -> OrganizationAnalyticsResponse:
    """Get detailed analytics for the current user's organization."""
    organization_id = current_user.organization.id
    data = await analytics_service.get_organization_analytics(organization_id)
    analytics_data = OrganizationAnalytics(**data)
    return OrganizationAnalyticsResponse(
        message_code=MessageCode.SUCCESS,
        message="Success",
        data=analytics_data,
    )


@router.get("/api-keys", response_model=APIKeyUsageResponse)
@require_permission(OrganizationPermission.VIEW_ANALYTICS)
async def get_api_key_usage_analytics(
    current_user: CurrentUserAuthDep,
    analytics_service: AnalyticsServiceDep,
    limit: int = Query(default=20, ge=1, le=100),
    days: int = Query(default=30, ge=1, le=365),
) -> APIKeyUsageResponse:
    """Get analytics for API key usage for the current user's organization."""
    organization_id = current_user.organization.id
    data = await analytics_service.get_api_key_usage_analytics(
        organization_id=organization_id, limit=limit, days=days
    )
    api_key_usage_data = [APIKeyUsage(**item) for item in data]
    return APIKeyUsageResponse(
        message_code=MessageCode.SUCCESS,
        message="Success",
        data=api_key_usage_data,
    )
