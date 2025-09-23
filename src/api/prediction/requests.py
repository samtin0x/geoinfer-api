"""Prediction domain requests and responses."""

from pydantic import BaseModel, HttpUrl

from src.api.core.exceptions.responses import APIResponse
from .models import PredictionResult


# Request Models
class PredictionUrlRequest(BaseModel):
    """Request for predicting from image URL."""

    image_url: HttpUrl


class PredictionUploadRequest(BaseModel):
    """Request for predicting from uploaded image."""

    # File upload will be handled separately in the endpoint
    pass


# Response Models
class PredictionResponse(BaseModel):
    """Complete prediction response."""

    prediction: PredictionResult


PredictionUrlResponse = APIResponse[PredictionResponse]
PredictionUploadResponse = APIResponse[PredictionResponse]
FreePredictionResponse = APIResponse[PredictionResult]
