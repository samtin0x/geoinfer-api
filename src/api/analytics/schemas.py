from enum import StrEnum
from pydantic import BaseModel
from src.api.core.messages import Paginated


class GroupByType(StrEnum):
    DAY = "day"
    HOUR = "hour"
    WEEK = "week"
    MONTH = "month"


class UsageTimeseries(BaseModel):
    period: str
    predictions: int
    credits_consumed: int
    unique_users: int


class UserUsage(BaseModel):
    user_id: str
    name: str
    email: str
    prediction_count: int
    credits_consumed: int


UserUsagePaginated = Paginated[UserUsage]


class OrganizationAnalytics(BaseModel):
    organization_id: str
    organization_name: str
    member_count: int
    total_predictions: int
    total_credits_consumed: int
    total_active_entities: int
    last_prediction_at: str | None
    api_key_predictions: int
    api_key_credits_consumed: int
    active_api_keys: int
    monthly_predictions: int
    monthly_credits_consumed: int
    monthly_active_entities: int
    monthly_api_key_predictions: int
    monthly_api_key_credits_consumed: int
    monthly_active_api_keys: int


class APIKeyUsage(BaseModel):
    api_key_id: str
    api_key_name: str
    prediction_count: int
    credits_consumed: int
    unique_users: int
    last_used_at: str | None


class DashboardStats(BaseModel):
    predictions: int
    credits_consumed: int
    active_users: int


class DashboardData(BaseModel):
    period_days: int
    timeseries: list[UsageTimeseries]
    user_usage: list[UserUsage]
    today_stats: DashboardStats
    generated_at: str
