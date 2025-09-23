from enum import StrEnum
from pydantic import BaseModel
from src.api.core.messages import Paginated


class GroupByType(StrEnum):
    """Enum for timeseries grouping options."""

    DAY = "day"
    HOUR = "hour"
    WEEK = "week"
    MONTH = "month"


class UsageTimeseries(BaseModel):
    """Model for usage timeseries data point."""

    period: str
    predictions: int
    credits_consumed: int
    unique_users: int


class UserUsage(BaseModel):
    """Model for user usage analytics data."""

    user_id: str
    name: str
    email: str
    prediction_count: int
    credits_consumed: int


UserUsagePaginated = Paginated[UserUsage]


class OrganizationAnalytics(BaseModel):
    """Model for organization analytics data."""

    organization_id: str
    organization_name: str
    member_count: int

    # Total statistics (user + API key usage)
    total_predictions: int
    total_credits_consumed: int
    total_active_entities: int
    last_prediction_at: str | None

    # API key usage statistics
    api_key_predictions: int
    api_key_credits_consumed: int
    active_api_keys: int

    # Monthly statistics (user + API key usage)
    monthly_predictions: int
    monthly_credits_consumed: int
    monthly_active_entities: int

    # Monthly API key statistics
    monthly_api_key_predictions: int
    monthly_api_key_credits_consumed: int
    monthly_active_api_keys: int


class APIKeyUsage(BaseModel):
    """Model for API key usage analytics."""

    api_key_id: str
    api_key_name: str
    prediction_count: int
    credits_consumed: int
    unique_users: int
    last_used_at: str | None


class DashboardStats(BaseModel):
    """Model for today's dashboard statistics."""

    predictions: int
    credits_consumed: int
    active_users: int


class DashboardData(BaseModel):
    """Model for dashboard analytics data."""

    period_days: int
    timeseries: list[UsageTimeseries]
    user_usage: list[UserUsage]
    today_stats: DashboardStats
    generated_at: str
