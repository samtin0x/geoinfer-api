"""Factory for Invitation models."""

import factory
from src.database.models import Invitation, InvitationStatus
from .base import AsyncSQLAlchemyModelFactory, UUIDFactory
from .organizations import OrganizationFactory
from .users import UserFactory


class InvitationFactory(AsyncSQLAlchemyModelFactory[Invitation]):
    """Factory for creating Invitation instances."""

    class Meta:
        model = Invitation

    id = UUIDFactory()
    organization_id = factory.SubFactory(OrganizationFactory)
    invited_by_id = factory.SubFactory(UserFactory)
    email = factory.Faker("email")
    status = factory.Faker("enum", enum_cls=InvitationStatus)
    token = factory.Faker("sha256")
    expires_at = factory.Faker("future_datetime", end_date="+30d")
    accepted_at = factory.Maybe(
        factory.LazyAttribute(lambda obj: obj.status == InvitationStatus.ACCEPTED),
        yes_declaration=factory.Faker("past_datetime", start_date="-30d"),
        no_declaration=None,
    )
    created_at = factory.Faker("date_time_this_year")
