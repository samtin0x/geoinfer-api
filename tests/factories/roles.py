"""Factory for UserOrganizationRole models."""

import factory
from src.database.models import UserOrganizationRole
from src.database.models.organizations import OrganizationRole
from .base import AsyncSQLAlchemyModelFactory, UUIDFactory
from .users import UserFactory
from .organizations import OrganizationFactory


class UserOrganizationRoleFactory(AsyncSQLAlchemyModelFactory[UserOrganizationRole]):
    """Factory for creating UserOrganizationRole instances."""

    class Meta:
        model = UserOrganizationRole

    id = UUIDFactory()
    user_id = factory.SubFactory(UserFactory)
    organization_id = factory.SubFactory(OrganizationFactory)
    role = factory.Faker("enum", enum_cls=OrganizationRole)
    granted_by_id = factory.SubFactory(UserFactory)
    granted_at = factory.Faker("date_time_this_year")
