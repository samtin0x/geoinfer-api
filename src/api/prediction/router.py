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
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    GLOBAL_MODEL_CREDIT_COST,
)
from src.api.core.decorators.auth import require_permission
from src.api.core.decorators.cost import cost

# No auth decorators needed - auth middleware sets request.state
from src.api.core.decorators.rate_limit import rate_limit
from src.api.core.exceptions.responses import APIResponse
from src.api.core.dependencies import AsyncSessionDep, CurrentUserAuthDep
from src.api.core.messages import APIResponse as CoreAPIResponse
from src.api.prediction.schemas import (
    PredictionResult,
    PredictionResponse,
    PredictionUploadResponse,
    FreePredictionResponse,
    PredictionHistoryPaginated,
)
from src.database.models import UsageType
from src.database.models.organizations import OrganizationPermission
from src.api.prediction.validators import validate_image_upload
from src.modules.prediction.application.use_cases import (
    predict_coordinates_from_upload,
    PredictionHistoryService,
)
from src.redis.client import get_redis_client

router = APIRouter(prefix="/prediction", tags=["prediction"])


@router.post("/predict", response_model=PredictionUploadResponse)
@rate_limit(
    limit=PRODUCTION_PREDICT_RATE_LIMIT,
    window_seconds=PRODUCTION_PREDICT_WINDOW_SECONDS,
)
@cost(credits=GLOBAL_MODEL_CREDIT_COST, usage_type=UsageType.GEOINFER_GLOBAL_0_0_1)
async def predict_location(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
    file: UploadFile = File(...),
    top_k: int = Query(default=DEFAULT_TOP_K, ge=MIN_TOP_K, le=MAX_TOP_K),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> APIResponse[PredictionResponse]:
    file_content = await validate_image_upload(file, 10 * 1024 * 1024)

    result = await predict_coordinates_from_upload(
        request=request,
        image_data=file_content,
        top_k=top_k,
        db=db,
        current_user=current_user,
        input_filename=file.filename,
        save_to_db=True,
        credits_consumed=GLOBAL_MODEL_CREDIT_COST,
        # TODO: Fix this endpoint to properly handle credits and usage type from decorator
        usage_type=UsageType.GEOINFER_GLOBAL_0_0_1,
    )

    return APIResponse.success_response(data=PredictionResponse(prediction=result))


@router.post("/trial", response_model=FreePredictionResponse)
@rate_limit(
    limit=PUBLIC_TRIAL_FREE_PREDICTIONS,
    window_seconds=PUBLIC_TRIAL_FREE_PREDICTIONS_WINDOW_SECONDS,
)
async def trial_prediction(
    request: Request,
    db: AsyncSessionDep,
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

    # Run prediction with top_k=1 for trial (no database saving)
    result = await predict_coordinates_from_upload(
        request=request,
        image_data=file_content,
        top_k=1,
        save_to_db=False,  # Trial predictions are not saved to database
    )

    return APIResponse.success_response(data=result)


@router.get("/history", response_model=PredictionHistoryPaginated)
@require_permission(OrganizationPermission.VIEW_ANALYTICS)
async def get_prediction_history(
    request: Request,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> PredictionHistoryPaginated:
    """Get paginated prediction history for the current user's organization.

    Returns predictions with details about who made them (user or API key),
    organization, credits consumed, model used, and timestamps.
    """
    prediction_service = PredictionHistoryService(db)
    paginated_predictions = await prediction_service.get_prediction_history(
        organization_id=current_user.organization.id, limit=limit, offset=offset
    )

    return CoreAPIResponse.success(data=paginated_predictions)
