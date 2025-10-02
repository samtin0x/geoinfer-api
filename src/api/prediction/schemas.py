"""Prediction API schemas (combined models/requests)."""

from pydantic import BaseModel, HttpUrl
from src.api.core.messages import APIResponse, Paginated


class LocationInfo(BaseModel):
    """Location information from reverse geocoding."""

    name: str  # City/place name
    admin1: str  # State/region
    admin2: str  # County/district
    country_code: str  # ISO country code


class Coordinates(BaseModel):

    latitude: float
    longitude: float


class CoordinatePrediction(Coordinates):
    confidence: float
    rank: int
    location: LocationInfo | None = None


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


class PredictionHistoryRecord(BaseModel):

    model_config = {"from_attributes": True}

    id: str
    organization_id: str
    user_id: str | None
    user_name: str | None
    api_key_id: str | None
    api_key_name: str | None
    processing_time_ms: int | None
    credits_consumed: int | None
    usage_type: str | None
    created_at: str

    @classmethod
    def from_prediction_row(
        cls, prediction, user_name: str | None = None, api_key_name: str | None = None
    ) -> "PredictionHistoryRecord":
        """Create a PredictionHistoryRecord from a Prediction ORM object and additional data."""
        return cls(
            id=str(prediction.id),
            organization_id=str(prediction.organization_id),
            user_id=str(prediction.user_id) if prediction.user_id else None,
            user_name=user_name,
            api_key_id=str(prediction.api_key_id) if prediction.api_key_id else None,
            api_key_name=api_key_name,
            processing_time_ms=prediction.processing_time_ms,
            credits_consumed=prediction.credits_consumed,
            usage_type=(
                prediction.usage_type.value
                if prediction.usage_type is not None
                and hasattr(prediction.usage_type, "value")
                else (
                    str(prediction.usage_type)
                    if prediction.usage_type is not None
                    else None
                )
            ),
            created_at=prediction.created_at.isoformat(),
        )


class PredictionHistoryResponse(BaseModel):
    """Paginated prediction history response."""

    predictions: Paginated[PredictionHistoryRecord]


PredictionUrlResponse = APIResponse[PredictionResponse]
PredictionUploadResponse = APIResponse[PredictionResponse]
FreePredictionResponse = APIResponse[PredictionResult]
PredictionHistoryPaginated = APIResponse[Paginated[PredictionHistoryRecord]]
