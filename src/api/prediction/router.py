"""Prediction endpoints router."""

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
import redis.asyncio as redis

from src.api.core.constants import (
    PRODUCTION_PREDICT_RATE_LIMIT,
    PRODUCTION_PREDICT_WINDOW_SECONDS,
    PUBLIC_TRIAL_FREE_PREDICTIONS,
    PUBLIC_TRIAL_FREE_PREDICTIONS_WINDOW_SECONDS,
    MIN_TOP_K,
    MAX_TOP_K,
    DEFAULT_TOP_K,
)
from src.api.core.decorators.cost import cost

# No auth decorators needed - auth middleware sets request.state
from src.api.core.decorators.rate_limit import rate_limit
from src.api.core.exceptions.responses import APIResponse
from src.api.prediction.schemas import (
    PredictionResult,
    PredictionResponse,
    PredictionUploadResponse,
    FreePredictionResponse,
)
from src.api.core.dependencies import AsyncSessionDep
from src.database.models import UsageType
from src.api.prediction.validators import validate_image_upload
from src.modules.prediction.application.use_cases import (
    predict_coordinates_from_upload,
)
from src.redis.client import get_redis_client

router = APIRouter(prefix="/prediction", tags=["prediction"])


@router.post("/predict", response_model=PredictionUploadResponse)
@rate_limit(
    limit=PRODUCTION_PREDICT_RATE_LIMIT,
    window_seconds=PRODUCTION_PREDICT_WINDOW_SECONDS,
)
@cost(usage_type=UsageType.GEOINFER_GLOBAL_0_0_1)
async def predict_location(
    request: Request,
    db: AsyncSessionDep,
    file: UploadFile = File(...),
    top_k: int = Query(default=DEFAULT_TOP_K, ge=MIN_TOP_K, le=MAX_TOP_K),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> APIResponse[PredictionResponse]:
    file_content = await validate_image_upload(file, 10 * 1024 * 1024)

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
    # Validate file (trial: 5MB cap)
    file_content = await validate_image_upload(file, 5 * 1024 * 1024)

    # Run prediction with top_k=1 for trial
    result = await predict_coordinates_from_upload(
        request=request, image_data=file_content, top_k=1
    )

    return APIResponse.success_response(data=result)
