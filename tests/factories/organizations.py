"""Factory for Organization models."""

import factory
from src.database.models import Organization, PlanTier
from .base import AsyncSQLAlchemyModelFactory, UUIDFactory


class OrganizationFactory(AsyncSQLAlchemyModelFactory[Organization]):
    """Factory for creating Organization instances."""

    class Meta:
        model = Organization

    id = UUIDFactory()
    name = factory.Faker("company")
    logo_url = factory.Faker("image_url", width=200, height=200)
    plan_tier = factory.Faker("enum", enum_cls=PlanTier)
    created_at = factory.Faker("date_time_this_year")
