"""Analytics request and response models."""

from src.api.core.messages import APIResponse
from .models import (
    UsageTimeseries,
    UserUsagePaginated,
    OrganizationAnalytics,
    APIKeyUsage,
    DashboardData,
)


class UsageTimeseriesResponse(APIResponse[list[UsageTimeseries]]):
    """Response for usage timeseries data."""

    pass


class OrganizationUserUsageResponse(APIResponse[UserUsagePaginated]):
    """Response for organization user usage analytics with pagination."""

    pass


class OrganizationAnalyticsResponse(APIResponse[OrganizationAnalytics]):
    """Response for organization analytics."""

    pass


class APIKeyUsageResponse(APIResponse[list[APIKeyUsage]]):
    """Response for API key usage analytics."""

    pass


class DashboardAnalyticsResponse(APIResponse[DashboardData]):
    """Response for dashboard overview analytics."""

    pass
