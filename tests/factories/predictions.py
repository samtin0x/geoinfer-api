"""Factory for Prediction models."""

import factory
from src.database.models import Prediction
from .base import AsyncSQLAlchemyModelFactory, UUIDFactory
from .users import UserFactory
from .organizations import OrganizationFactory


class PredictionFactory(AsyncSQLAlchemyModelFactory[Prediction]):
    """Factory for creating Prediction instances."""

    class Meta:
        model = Prediction

    id = UUIDFactory()
    user_id = factory.SubFactory(UserFactory)
    organization_id = factory.SubFactory(OrganizationFactory)
    input_type = factory.Faker("random_element", elements=["url", "upload"])
    input_data = factory.LazyAttribute(
        lambda obj: (
            factory.Faker("url").generate()
            if obj.input_type == "url"
            else factory.Faker("file_path", depth=2).generate()
        )
    )
    prediction_result = factory.Faker("json")
    processing_time_ms = factory.Faker("random_int", min=100, max=5000)
    status = factory.Faker(
        "random_element", elements=["completed", "failed", "processing"]
    )
    error_message = factory.Maybe(
        factory.LazyAttribute(lambda obj: obj.status == "failed"),
        yes_declaration=factory.Faker("sentence"),
        no_declaration=None,
    )
    created_at = factory.Faker("date_time_this_year")
    updated_at = factory.Faker("date_time_this_year")
