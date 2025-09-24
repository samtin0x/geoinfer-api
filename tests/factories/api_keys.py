"""Factory for ApiKey models."""

import factory
from src.database.models import ApiKey
from .base import AsyncSQLAlchemyModelFactory, UUIDFactory
from .users import UserFactory


class ApiKeyFactory(AsyncSQLAlchemyModelFactory[ApiKey]):
    """Factory for creating ApiKey instances."""

    class Meta:
        model = ApiKey

    id = UUIDFactory()
    name = factory.Faker("word")
    key_hash = factory.Faker("sha256")
    user_id = factory.SubFactory(UserFactory)
    last_used_at = factory.Faker("date_time_this_month", tzinfo=None)
    created_at = factory.Faker("date_time_this_year")
