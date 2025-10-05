"""Prediction API schemas (combined models/requests)."""

from uuid import UUID

from pydantic import BaseModel, HttpUrl
from src.api.core.messages import APIResponse, Paginated
from src.database.models.feedback import FeedbackType


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


class PredictionUrlRequest(BaseModel):
    image_url: HttpUrl


class PredictionUploadRequest(BaseModel):
    pass


class PredictionResponse(BaseModel):
    prediction: PredictionResult
    prediction_id: UUID


class PredictionHistoryRecord(BaseModel):

    model_config = {"from_attributes": True}

    id: UUID
    organization_id: UUID
    user_id: UUID | None
    user_name: str | None
    api_key_id: UUID | None
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
            id=prediction.id,
            organization_id=prediction.organization_id,
            user_id=prediction.user_id if prediction.user_id else None,
            user_name=user_name,
            api_key_id=prediction.api_key_id if prediction.api_key_id else None,
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


class CreateShareRequest(BaseModel):
    prediction_id: UUID
    result_data: PredictionResult


class SharedPredictionResponse(BaseModel):
    prediction_id: UUID
    share_url: str
    result_data: PredictionResult
    image_url: str
    is_active: bool
    created_at: str


class FeedbackRequest(BaseModel):
    feedback: FeedbackType
    comment: str | None = None


PredictionUrlResponse = APIResponse[PredictionResponse]
PredictionUploadResponse = APIResponse[PredictionResponse]
FreePredictionResponse = APIResponse[PredictionResult]
PredictionHistoryPaginated = APIResponse[Paginated[PredictionHistoryRecord]]
CreateShareResponse = APIResponse[SharedPredictionResponse]
GetSharedPredictionResponse = APIResponse[SharedPredictionResponse]
AddFeedbackResponse = APIResponse[bool]
