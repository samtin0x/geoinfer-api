"""Prediction endpoints router."""

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from src.api.core.constants import (
    PRODUCTION_PREDICT_RATE_LIMIT,
    PRODUCTION_PREDICT_WINDOW_SECONDS,
    PUBLIC_TRIAL_FREE_PREDICTIONS,
    PUBLIC_TRIAL_FREE_PREDICTIONS_WINDOW_SECONDS,
    MIN_TOP_K,
    MAX_TOP_K,
    DEFAULT_TOP_K,
    PREDICTION_DATA_TYPES,
    HEIC_HEIF_EXTENSIONS,
)
from src.api.core.decorators.cost import cost

# No auth decorators needed - auth middleware sets request.state
from src.api.core.decorators.rate_limit import rate_limit
from src.api.core.exceptions.base import GeoInferException
from src.api.core.exceptions.responses import APIResponse
from src.api.core.messages import MessageCode
from src.api.prediction.models import PredictionResult
from src.api.prediction.requests import (
    PredictionResponse,
    PredictionUploadResponse,
    FreePredictionResponse,
)
from src.database.connection import get_db_dependency
from src.database.models import UsageType
from src.services.prediction.service import (
    predict_coordinates_from_upload,
)
from src.services.redis_service import get_redis_client

router = APIRouter(prefix="/prediction", tags=["prediction"])


@router.post("/predict", response_model=PredictionUploadResponse)
@rate_limit(
    limit=PRODUCTION_PREDICT_RATE_LIMIT,
    window_seconds=PRODUCTION_PREDICT_WINDOW_SECONDS,
)
@cost(usage_type=UsageType.GEOINFER_GLOBAL_0_0_1)
async def predict_location(
    request: Request,
    file: UploadFile = File(...),
    top_k: int = DEFAULT_TOP_K,
    db: AsyncSession = Depends(get_db_dependency),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> APIResponse[PredictionResponse]:
    """
    Predict location from uploaded image.
    Requires authentication (user or API key).
    Automatically consumes 1 credit on successful prediction.
    """
    # Validate top_k parameter
    if not MIN_TOP_K <= top_k <= MAX_TOP_K:
        raise GeoInferException(
            MessageCode.BAD_REQUEST,
            status.HTTP_400_BAD_REQUEST,
            details={
                "description": f"top_k must be between {MIN_TOP_K} and {MAX_TOP_K}"
            },
        )

    if not file.content_type or (
        not file.content_type.startswith("image/")
        and file.content_type not in PREDICTION_DATA_TYPES
    ):
        # For files with generic content types, check the filename extension
        if file.filename and file.filename.lower().endswith(HEIC_HEIF_EXTENSIONS):
            # Allow HEIC/HEIF files even with generic content types
            pass
        else:
            raise GeoInferException(
                MessageCode.INVALID_FILE_TYPE, status.HTTP_400_BAD_REQUEST
            )

    # Validate file size (max 10MB)
    max_size = 10 * 1024 * 1024
    file_content = await file.read()
    if len(file_content) > max_size:
        raise GeoInferException(MessageCode.FILE_TOO_LARGE, status.HTTP_400_BAD_REQUEST)

    # Run prediction - credits are handled by the @cost decorator
    result = await predict_coordinates_from_upload(
        request=request, image_data=file_content, top_k=top_k
    )

    return APIResponse.success_response(data=PredictionResponse(prediction=result))


@router.post("/trial", response_model=FreePredictionResponse)
@rate_limit(
    limit=PUBLIC_TRIAL_FREE_PREDICTIONS,
    window_seconds=PUBLIC_TRIAL_FREE_PREDICTIONS_WINDOW_SECONDS,
)
async def trial_prediction(
    request: Request,
    file: UploadFile = File(...),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> APIResponse[PredictionResult]:
    """
    Trial prediction endpoint (no authentication required).
    Limited functionality - returns only top prediction.
    Rate limited to 3 requests per day per IP address.
    """
    # Validate file type - must be an image (including HEIC/HEIF)
    if not file.content_type or (
        not file.content_type.startswith("image/")
        and file.content_type not in PREDICTION_DATA_TYPES
    ):
        # For files with generic content types, check the filename extension
        if file.filename and file.filename.lower().endswith(HEIC_HEIF_EXTENSIONS):
            # Allow HEIC/HEIF files even with generic content types
            pass
        else:
            raise GeoInferException(
                MessageCode.INVALID_FILE_TYPE, status.HTTP_400_BAD_REQUEST
            )

    # Validate file size (max 5MB for trial)
    max_size = 5 * 1024 * 1024
    file_content = await file.read()
    if len(file_content) > max_size:
        raise GeoInferException(MessageCode.FILE_TOO_LARGE, status.HTTP_400_BAD_REQUEST)

    # Run prediction with top_k=1 for trial
    result = await predict_coordinates_from_upload(
        request=request, image_data=file_content, top_k=1
    )

    return APIResponse.success_response(data=result)
