"""Factory for UsageRecord models."""

import factory
from src.database.models import UsageRecord, UsageType, OperationType
from .base import AsyncSQLAlchemyModelFactory, UUIDFactory


class UsageRecordFactory(AsyncSQLAlchemyModelFactory[UsageRecord]):
    """Factory for creating UsageRecord instances."""

    class Meta:
        model = UsageRecord

    id = UUIDFactory()
    user_id = UUIDFactory()
    credits_consumed = factory.Faker("random_int", min=1, max=100)
    usage_type = factory.Faker("enum", enum_cls=UsageType)
    api_key_id = UUIDFactory()
    organization_id = UUIDFactory()
    subscription_id = UUIDFactory()
    topup_id = UUIDFactory()
    operation_type = factory.Faker("enum", enum_cls=OperationType)
    created_at = factory.Faker("date_time_this_year")
