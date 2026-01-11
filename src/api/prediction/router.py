from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    Request,
    UploadFile,
    status,
)

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
)
from src.api.core.decorators.auth import require_permission
from src.api.core.decorators.cost import cost
import redis.asyncio as redis

# No auth decorators needed - auth middleware sets request.state
from src.api.core.decorators.rate_limit import rate_limit, get_client_ip
from src.api.core.dependencies import (
    AsyncSessionDep,
    CurrentUserAuthDep,
    GPUServerClientDep,
    R2ClientDep,
)
from src.api.core.messages import APIResponse, MessageCode
from src.api.core.exceptions.base import GeoInferException
from src.api.prediction.schemas import (
    PredictionResponse,
    PredictionUploadResponse,
    FreePredictionResponse,
    CoordinatePrediction,
    CoordinatePredictionResult,
    LocationInfo,
    Coordinates,
    PredictionHistoryPaginated,
    SharedPredictionResponse,
    CreateShareResponse,
    GetSharedPredictionResponse,
    FeedbackRequest,
    AddFeedbackResponse,
    parse_prediction_result,
)
from src.database.models.organizations import OrganizationPermission
from src.database.models.usage import ModelType
from src.api.prediction.validators import validate_image_upload
from src.modules.prediction.application.use_cases import (
    predict_from_upload,
    PredictionHistoryService,
)
from src.modules.prediction.feedback import SharingService
from src.modules.prediction.models import (
    ModelId,
    ModelConfig,
    get_enabled_models,
)
from src.redis.client import get_redis_client
from src.utils.path_helpers import build_r2_image_metadata
import reverse_geocoder as rg


router = APIRouter(prefix="/prediction", tags=["prediction"])

TRIAL_ORG_ID = UUID("00000000-0000-0000-0000-000000000000")


@router.post("/enrich-locations")
async def enrich_locations(
    coords: list[Coordinates],
) -> APIResponse[list[LocationInfo | None]]:
    if not coords:
        return APIResponse.success(data=[])

    tuples = [(c.latitude, c.longitude) for c in coords]
    results = rg.search(tuples)

    payload: list[LocationInfo | None] = []
    for place in results:
        if not place:
            payload.append(None)
            continue
        payload.append(
            LocationInfo(
                name=place.get("name", ""),
                admin1=place.get("admin1", ""),
                admin2=place.get("admin2", ""),
                country_code=place.get("cc", ""),
            )
        )

    return APIResponse.success(data=payload)


@router.get("/models")
async def get_available_models() -> APIResponse[list[ModelConfig]]:
    """Get list of available prediction models and their configurations."""
    return APIResponse.success(data=get_enabled_models())


@router.post("/predict", response_model=PredictionUploadResponse)
@rate_limit(
    limit=PRODUCTION_PREDICT_RATE_LIMIT,
    window_seconds=PRODUCTION_PREDICT_WINDOW_SECONDS,
)
@cost()
async def predict(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
    gpu_client: GPUServerClientDep,
    r2_client: R2ClientDep,
    file: UploadFile = File(...),
    model_id: ModelId = Query(
        default=ModelId.GLOBAL_V0_1, description="Model to use for prediction"
    ),
    top_k: int = Query(default=DEFAULT_TOP_K, ge=MIN_TOP_K, le=MAX_TOP_K),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> APIResponse[PredictionResponse]:
    """
    Run prediction on an uploaded image using the specified model.

    Returns different result types based on model:
    - Global/Accuracy: Coordinate predictions (geolocation)
    - Cars: Vehicle identification (make/model/year)
    - Property: Hotel/vacation rental matching

    Credit costs by model type:
    - Global: 1 credit
    - Cars: 2 credits
    - Property: 3 credits
    - Accuracy: 3 credits
    """
    file_content = await validate_image_upload(file, 10 * 1024 * 1024)

    # Access credits/model_type from request.state (set by @cost decorator)
    credits_consumed = request.state.credits_to_consume
    model_type = request.state.model_type

    result, prediction_id = await predict_from_upload(
        request=request,
        image_data=file_content,
        gpu_client=gpu_client,
        model_type=model_type,
        top_k=top_k,
        db=db,
        current_user=current_user,
        input_filename=file.filename,
        save_to_db=True,
        credits_consumed=credits_consumed,
        model_id=model_id,
    )

    # Extract top prediction for metadata (only coordinate models have lat/lng)
    top_pred: CoordinatePrediction | None = None
    if model_type in (ModelType.GLOBAL, ModelType.ACCURACY) and result.predictions:
        top_pred = result.predictions[0]  # type: ignore[assignment]

    background_tasks.add_task(
        r2_client.upload_prediction_image,
        image_data=file_content,
        organization_id=current_user.organization.id,
        filename=file.filename or "image.bin",
        prediction_id=prediction_id,
        ip_address=get_client_ip(request),
        extra_metadata=build_r2_image_metadata(
            top_prediction=top_pred,
            prediction_id=prediction_id,
            model_id=model_id,
            model_type=model_type,
        ),
    )

    return APIResponse.success(
        data=PredictionResponse(
            prediction=result,
            prediction_id=prediction_id,
            model_id=model_id,
            credits_consumed=credits_consumed,
        )
    )


@router.post("/trial", response_model=FreePredictionResponse)
@rate_limit(
    limit=PUBLIC_TRIAL_FREE_PREDICTIONS,
    window_seconds=PUBLIC_TRIAL_FREE_PREDICTIONS_WINDOW_SECONDS,
)
async def trial_predict_location(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSessionDep,
    gpu_client: GPUServerClientDep,
    r2_client: R2ClientDep,
    file: UploadFile = File(...),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> APIResponse[CoordinatePredictionResult]:
    """
    Free trial geolocation prediction (no authentication required).

    Uses Global model only, returns top coordinate prediction.
    Rate limited to 3 requests per day per IP address.
    Results are not saved to database.
    """
    file_content = await validate_image_upload(file, 5 * 1024 * 1024)

    result, _ = await predict_from_upload(
        request=request,
        image_data=file_content,
        gpu_client=gpu_client,
        model_type=ModelType.GLOBAL,
        top_k=1,
        save_to_db=False,
    )

    # Global model always returns CoordinatePredictionResult
    coord_result: CoordinatePredictionResult = result  # type: ignore[assignment]
    top_pred = coord_result.predictions[0] if coord_result.predictions else None

    background_tasks.add_task(
        r2_client.upload_prediction_image,
        image_data=file_content,
        organization_id=TRIAL_ORG_ID,
        filename=file.filename or "image.bin",
        ip_address=get_client_ip(request),
        extra_metadata=build_r2_image_metadata(top_prediction=top_pred),
    )

    return APIResponse.success(data=coord_result)


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

    return APIResponse.success(data=paginated_predictions)


@router.post(
    "/{prediction_id}/share",
    response_model=CreateShareResponse,
    tags=["prediction-sharing"],
)
@require_permission(OrganizationPermission.VIEW_ANALYTICS)
async def create_prediction_share(
    request: Request,
    prediction_id: UUID,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
    r2_client: R2ClientDep,
    result_data: str = Form(...),
    file: UploadFile = File(...),
) -> APIResponse[SharedPredictionResponse]:
    """Create a shareable link for a prediction.

    Expects:
    - result_data: JSON string of PredictionResult
    - file: Original image file
    """
    sharing_service = SharingService(db)
    shared = await sharing_service.create_share(
        prediction_id=prediction_id,
        result_data_json=result_data,
        file=file,
        r2_client=r2_client,
        user=current_user,
    )

    share_url = f"/?predictionId={prediction_id}"
    image_url = await r2_client.generate_signed_url(
        key=shared.image_key, expiry_seconds=86400
    )

    if not image_url:
        raise GeoInferException(
            MessageCode.EXTERNAL_SERVICE_ERROR,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"description": "Failed to generate image URL"},
        )

    return APIResponse.success(
        message_code=MessageCode.SHARE_CREATED,
        data=SharedPredictionResponse(
            prediction_id=UUID(str(shared.prediction_id)),
            share_url=share_url,
            result_data=parse_prediction_result(shared.result_data),
            image_url=image_url,
            is_active=shared.is_active,
            created_at=shared.created_at.isoformat(),
        ),
    )


@router.get(
    "/{prediction_id}/share",
    response_model=GetSharedPredictionResponse,
    tags=["prediction-sharing"],
)
async def get_shared_prediction(
    request: Request,
    prediction_id: UUID,
    db: AsyncSessionDep,
    r2_client: R2ClientDep,
) -> APIResponse[SharedPredictionResponse]:
    """Public endpoint to view a shared prediction (no auth required)."""

    sharing_service = SharingService(db)
    shared = await sharing_service.get_shared_prediction(prediction_id)

    if not shared:
        raise GeoInferException(MessageCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)

    image_url = await r2_client.generate_signed_url(
        key=shared.image_key, expiry_seconds=3600
    )

    if not image_url:
        raise GeoInferException(
            MessageCode.EXTERNAL_SERVICE_ERROR,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"description": "Failed to generate image URL"},
        )

    share_url = f"/?predictionId={prediction_id}"

    return APIResponse.success(
        data=SharedPredictionResponse(
            prediction_id=UUID(str(shared.prediction_id)),
            share_url=share_url,
            result_data=parse_prediction_result(shared.result_data),
            image_url=image_url,
            is_active=shared.is_active,
            created_at=shared.created_at.isoformat(),
        )
    )


@router.post(
    "/{prediction_id}/feedback",
    response_model=AddFeedbackResponse,
    tags=["prediction-sharing"],
)
async def add_prediction_feedback(
    request: Request,
    prediction_id: UUID,
    feedback_request: FeedbackRequest,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> AddFeedbackResponse:
    """Add feedback to a prediction (requires authentication)."""

    sharing_service = SharingService(db)

    await sharing_service.add_feedback(
        prediction_id=prediction_id,
        feedback=feedback_request.feedback,
        comment=feedback_request.comment,
    )

    return APIResponse.success(message_code=MessageCode.FEEDBACK_ADDED, data=True)


@router.delete(
    "/{prediction_id}/share",
    response_model=APIResponse[None],
    tags=["prediction-sharing"],
)
async def revoke_prediction_share(
    request: Request,
    prediction_id: UUID,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> APIResponse[None]:
    """Revoke a shared prediction."""

    sharing_service = SharingService(db)
    revoked = await sharing_service.revoke_share(prediction_id, current_user)

    if not revoked:
        raise GeoInferException(MessageCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)

    return APIResponse.success(message_code=MessageCode.SHARE_REVOKED)
