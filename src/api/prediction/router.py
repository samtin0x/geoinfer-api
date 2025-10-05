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
    GLOBAL_MODEL_CREDIT_COST,
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
    PredictionResult,
    PredictionResponse,
    PredictionUploadResponse,
    FreePredictionResponse,
    LocationInfo,
    Coordinates,
    PredictionHistoryPaginated,
    SharedPredictionResponse,
    CreateShareResponse,
    GetSharedPredictionResponse,
    FeedbackRequest,
    AddFeedbackResponse,
)
from src.database.models import UsageType
from src.database.models.organizations import OrganizationPermission
from src.api.prediction.validators import validate_image_upload
from src.modules.prediction.application.use_cases import (
    predict_coordinates_from_upload,
    PredictionHistoryService,
)
from src.modules.prediction.feedback import SharingService
from src.redis.client import get_redis_client
from src.utils.path_helpers import build_prediction_metadata
import reverse_geocoder as rg


router = APIRouter(prefix="/prediction", tags=["prediction"])

TRIAL_ORG_ID = UUID("00000000-0000-0000-0000-000000000000")


@router.post("/enrich-locations")
async def enrich_locations(
    coords: list[Coordinates],
) -> APIResponse[list[LocationInfo | None]]:
    if not coords:
        return APIResponse.success(data=[])

    tuples = [(float(c.latitude), float(c.longitude)) for c in coords]
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


@router.post("/predict", response_model=PredictionUploadResponse)
@rate_limit(
    limit=PRODUCTION_PREDICT_RATE_LIMIT,
    window_seconds=PRODUCTION_PREDICT_WINDOW_SECONDS,
)
@cost(credits=GLOBAL_MODEL_CREDIT_COST, usage_type=UsageType.GEOINFER_GLOBAL_0_0_1)
async def predict_location(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
    gpu_client: GPUServerClientDep,
    r2_client: R2ClientDep,
    file: UploadFile = File(...),
    top_k: int = Query(default=DEFAULT_TOP_K, ge=MIN_TOP_K, le=MAX_TOP_K),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> APIResponse[PredictionResponse]:
    file_content = await validate_image_upload(file, 10 * 1024 * 1024)

    result, prediction_id = await predict_coordinates_from_upload(
        request=request,
        image_data=file_content,
        top_k=top_k,
        db=db,
        current_user=current_user,
        gpu_client=gpu_client,
        input_filename=file.filename,
        save_to_db=True,
        credits_consumed=GLOBAL_MODEL_CREDIT_COST,
        # TODO: Fix this endpoint to properly handle credits and usage type from decorator
        usage_type=UsageType.GEOINFER_GLOBAL_0_0_1,
    )

    top_pred = result.predictions[0] if result.predictions else None
    background_tasks.add_task(
        r2_client.upload_prediction_image,
        image_data=file_content,
        organization_id=current_user.organization.id,
        filename=file.filename or "image.bin",
        prediction_id=prediction_id,
        ip_address=get_client_ip(request),
        extra_metadata=build_prediction_metadata(
            top_prediction=top_pred,
            prediction_id=prediction_id,
        ),
    )

    return APIResponse.success(
        data=PredictionResponse(prediction=result, prediction_id=prediction_id)
    )


@router.post("/trial", response_model=FreePredictionResponse)
@rate_limit(
    limit=PUBLIC_TRIAL_FREE_PREDICTIONS,
    window_seconds=PUBLIC_TRIAL_FREE_PREDICTIONS_WINDOW_SECONDS,
)
async def trial_prediction(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSessionDep,
    gpu_client: GPUServerClientDep,
    r2_client: R2ClientDep,
    file: UploadFile = File(...),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> APIResponse[PredictionResult]:
    """
    Trial prediction endpoint (no authentication required).
    Limited functionality - returns only top prediction.
    Rate limited to 3 requests per day per IP address.
    Note: Trial predictions are not uploaded to R2 storage.
    """
    # Validate file (trial: 5MB cap)
    file_content = await validate_image_upload(file, 5 * 1024 * 1024)

    result, _ = await predict_coordinates_from_upload(
        request=request,
        image_data=file_content,
        top_k=1,
        gpu_client=gpu_client,
        save_to_db=False,  # Trial predictions are not saved to database
    )

    top_pred = result.predictions[0] if result.predictions else None
    background_tasks.add_task(
        r2_client.upload_prediction_image,
        image_data=file_content,
        organization_id=TRIAL_ORG_ID,
        filename=file.filename or "image.bin",
        ip_address=get_client_ip(request),
        extra_metadata=build_prediction_metadata(top_prediction=top_pred),
    )

    return APIResponse.success(data=result)


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
            result_data=PredictionResult(**shared.result_data),
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
            result_data=PredictionResult(**shared.result_data),
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
