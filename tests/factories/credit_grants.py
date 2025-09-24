"""Factory for CreditGrant models."""

import factory
from src.database.models import CreditGrant, GrantType
from .base import AsyncSQLAlchemyModelFactory, UUIDFactory
from .organizations import OrganizationFactory


class CreditGrantFactory(AsyncSQLAlchemyModelFactory[CreditGrant]):
    """Factory for creating CreditGrant instances."""

    class Meta:
        model = CreditGrant

    id = UUIDFactory()
    organization_id = factory.SubFactory(OrganizationFactory)
    subscription_id = None  # Set via SubFactory when needed
    topup_id = None  # Set via SubFactory when needed
    grant_type = factory.Faker("enum", enum_cls=GrantType)
    description = factory.Faker("sentence")
    amount = factory.Faker("random_int", min=100, max=10000)
    remaining_amount = factory.LazyAttribute(lambda obj: obj.amount)
    expires_at = factory.Maybe(
        factory.LazyAttribute(
            lambda obj: obj.grant_type in [GrantType.TRIAL, GrantType.TOPUP]
        ),
        yes_declaration=factory.Faker("future_datetime", end_date="+365d"),
        no_declaration=None,
    )
    created_at = factory.Faker("date_time_this_year")
