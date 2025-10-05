"""Factory for PredictionFeedback models."""

import factory
from src.database.models import PredictionFeedback, FeedbackType
from .base import AsyncSQLAlchemyModelFactory
from .predictions import PredictionFactory


class PredictionFeedbackFactory(AsyncSQLAlchemyModelFactory[PredictionFeedback]):
    """Factory for creating PredictionFeedback instances."""

    class Meta:
        model = PredictionFeedback

    prediction_id = factory.SubFactory(PredictionFactory)
    feedback = factory.Faker(
        "random_element",
        elements=[FeedbackType.CORRECT, FeedbackType.INCORRECT, FeedbackType.CLOSE],
    )
    comment = factory.Faker("sentence", nb_words=10)
    created_at = factory.Faker("date_time_this_year")
