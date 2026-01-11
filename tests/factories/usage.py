"""Factory for UsageRecord and UsagePeriod models."""

import factory
from src.database.models import UsageRecord, ModelType, OperationType, UsagePeriod
from .base import AsyncSQLAlchemyModelFactory, UUIDFactory


class UsageRecordFactory(AsyncSQLAlchemyModelFactory[UsageRecord]):
    """Factory for creating UsageRecord instances."""

    class Meta:
        model = UsageRecord

    id = UUIDFactory()
    user_id = UUIDFactory()
    credits_consumed = factory.Faker("random_int", min=1, max=100)
    model_type = factory.Faker("enum", enum_cls=ModelType)
    model_id = factory.Faker(
        "random_element", elements=["global_v0.1", "madrid_v0.1", "la_palma_v0.1"]
    )
    api_key_id = UUIDFactory()
    organization_id = UUIDFactory()
    subscription_id = UUIDFactory()
    topup_id = UUIDFactory()
    operation_type = factory.Faker("enum", enum_cls=OperationType)
    created_at = factory.Faker("date_time_this_year")


class UsagePeriodFactory(AsyncSQLAlchemyModelFactory[UsagePeriod]):
    """Factory for creating UsagePeriod instances."""

    class Meta:
        model = UsagePeriod

    id = UUIDFactory()
    subscription_id = None  # Set via SubFactory when needed
    period_start = factory.Faker("past_datetime", start_date="-30d")
    period_end = factory.Faker("future_datetime", end_date="+30d")
    overage_used = factory.Faker("random_int", min=0, max=1000)
    overage_reported = factory.Faker("random_int", min=0, max=1000)
    closed = factory.Faker("boolean")
    created_at = factory.Faker("date_time_this_year")
    updated_at = factory.Faker("date_time_this_year")
