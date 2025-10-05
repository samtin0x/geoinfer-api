"""Factory for SharedPrediction models."""

import factory
from src.database.models import SharedPrediction
from .base import AsyncSQLAlchemyModelFactory
from .predictions import PredictionFactory


class SharedPredictionFactory(AsyncSQLAlchemyModelFactory[SharedPrediction]):
    """Factory for creating SharedPrediction instances."""

    class Meta:
        model = SharedPrediction

    prediction_id = factory.SubFactory(PredictionFactory)
    result_data = factory.LazyFunction(
        lambda: {
            "coordinates": {"lat": 51.5074, "lng": -0.1278},
            "confidence": 0.95,
            "location_info": {
                "city": "London",
                "country": "United Kingdom",
                "region": "England",
            },
        }
    )
    image_key = factory.Sequence(
        lambda n: f"raw/organization/test-org-id/test-image-{n}.jpg"
    )
    is_active = True
    created_at = factory.Faker("date_time_this_year")
    updated_at = factory.Faker("date_time_this_year")
