"""Prediction API schemas (combined models/requests)."""

from pydantic import BaseModel, HttpUrl
from src.api.core.exceptions.responses import APIResponse


class CoordinatePrediction(BaseModel):
    latitude: float
    longitude: float
    confidence: float
    rank: int


class PredictionResult(BaseModel):
    predictions: list[CoordinatePrediction]
    processing_time_ms: int
    top_prediction: CoordinatePrediction | None = None


class PredictionUrlRequest(BaseModel):
    image_url: HttpUrl


class PredictionUploadRequest(BaseModel):
    pass


class PredictionResponse(BaseModel):
    prediction: PredictionResult


PredictionUrlResponse = APIResponse[PredictionResponse]
PredictionUploadResponse = APIResponse[PredictionResponse]
FreePredictionResponse = APIResponse[PredictionResult]
