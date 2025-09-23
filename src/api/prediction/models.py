"""Prediction domain models."""

from pydantic import BaseModel, HttpUrl


class CoordinatePrediction(BaseModel):
    """Single coordinate prediction."""

    latitude: float
    longitude: float
    confidence: float
    rank: int


class PredictionResult(BaseModel):
    """Complete prediction result with multiple predictions."""

    predictions: list[CoordinatePrediction]
    processing_time_ms: int
    top_prediction: CoordinatePrediction | None = (
        None  # Convenience field for the best prediction
    )


class PredictionRequest(BaseModel):
    """Request for image prediction."""

    image_url: HttpUrl
    top_k: int = 5  # Number of predictions to return
