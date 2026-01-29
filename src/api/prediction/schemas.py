"""Prediction API schemas (combined models/requests)."""

from enum import Enum
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, TypeAdapter

from src.api.core.messages import APIResponse, Paginated
from src.database.models.feedback import FeedbackType
from src.database.models.usage import ModelType
from src.modules.prediction.models import ModelId


# ============================================================
# Shared Models
# ============================================================


class Coordinates(BaseModel):
    """Coordinates model."""

    latitude: float
    longitude: float


# ============================================================
# Global / Accuracy Models (Coordinate-based)
# ============================================================


class LocationInfo(BaseModel):
    """Location information from reverse geocoding."""

    name: str  # City/place name
    admin1: str  # State/region
    admin2: str  # County/district
    country_code: str  # ISO country code


class LocationCluster(BaseModel):
    """A geographic cluster of prediction points."""

    center: Coordinates
    location: LocationInfo  # Reverse geocoded from center
    radius_km: float  # Distance from center to furthest point (max 25km)
    points: list[Coordinates]  # Individual prediction points in cluster


class CoordinatePredictionResult(BaseModel):
    """Result from Global/Accuracy prediction request."""

    result_type: Literal["coordinates"] = "coordinates"
    clusters: list[LocationCluster]
    processing_time_ms: int


# ============================================================
# Cars Model (Vehicle Recognition)
# ============================================================


class VehiclePrediction(BaseModel):
    """Single vehicle match result."""

    make: str  # e.g., "Mercedes-Benz"
    model: str  # e.g., "S-Class"
    year: str  # e.g., "2023" or "2020-2023"
    confidence: float  # 0-100 percentage
    variant: str | None = None  # e.g., "S 580 4MATIC"
    images: list[str] = []  # Reference image URLs


class VehiclePredictionResult(BaseModel):
    """Result from Cars prediction request.

    TODO: Remove placeholder once GPU server supports vehicle recognition.
    """

    result_type: Literal["vehicle"] = "vehicle"
    predictions: list[VehiclePrediction]
    processing_time_ms: int


# ============================================================
# Property Model (Hotels & Vacation Rentals)
# ============================================================


class PropertyCategory(str, Enum):
    HOTEL = "hotel"
    VACATION_RENTAL = "vacation_rental"


class PropertyPrediction(BaseModel):
    """Single property match result."""

    name: str  # e.g., "Grand Hyatt Tokyo"
    location: str  # e.g., "Roppongi Hills, Tokyo"
    country: str  # e.g., "Japan"
    coordinates: Coordinates
    confidence: float  # 0-100 percentage
    category: PropertyCategory
    address: str | None = None  # Full street address
    images: list[str] = []  # Reference image URLs


class PropertyPredictionResult(BaseModel):
    """Result from Property prediction request.

    TODO: Remove placeholder once GPU server supports property recognition.
    """

    result_type: Literal["property"] = "property"
    predictions: list[PropertyPrediction]
    processing_time_ms: int


# ============================================================
# Discriminated Union for PredictionResult
# ============================================================

PredictionResult = Annotated[
    Union[
        CoordinatePredictionResult,
        VehiclePredictionResult,
        PropertyPredictionResult,
    ],
    Field(discriminator="result_type"),
]


def parse_prediction_result(
    data: dict[str, Any],
) -> CoordinatePredictionResult | VehiclePredictionResult | PropertyPredictionResult:
    """Parse dict/JSON into the correct PredictionResult type using discriminator."""
    return TypeAdapter(PredictionResult).validate_python(data)


# ============================================================
# API Request/Response Models
# ============================================================


class PredictionUrlRequest(BaseModel):
    image_url: HttpUrl


class PredictionUploadRequest(BaseModel):
    pass


class PredictionResponse(BaseModel):
    prediction: PredictionResult
    prediction_id: UUID
    model_id: ModelId
    credits_consumed: int


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
    model_type: ModelType | None
    model_id: ModelId | None
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
            model_type=(
                ModelType(prediction.model_type) if prediction.model_type else None
            ),
            model_id=ModelId(prediction.model_id) if prediction.model_id else None,
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
