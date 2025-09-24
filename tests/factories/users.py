"""Factory for User models."""

import factory
from src.database.models import User
from .base import AsyncSQLAlchemyModelFactory, UUIDFactory
from .organizations import OrganizationFactory


class UserFactory(AsyncSQLAlchemyModelFactory[User]):
    """Factory for creating User instances."""

    class Meta:
        model = User

    id = UUIDFactory()
    name = factory.Faker("name")
    email = factory.Faker("email")
    organization_id = factory.SubFactory(OrganizationFactory)
    created_at = factory.Faker("date_time_this_year")
    updated_at = factory.Faker("date_time_this_year")
    avatar_url = factory.Faker("image_url", width=100, height=100)
    locale = factory.Faker("random_element", elements=["en", "es", "fr", "de", "it"])
