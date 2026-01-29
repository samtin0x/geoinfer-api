import logging
import time
import uuid
from uuid import UUID

from fastapi import Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode, Paginated, PaginationInfo
from src.core.context import AuthenticatedUserContext
from src.api.prediction.schemas import (
    PredictionResult,
    PredictionHistoryRecord,
)
from src.core.base import BaseService
from src.database.models.predictions import Prediction
from src.database.models.users import User
from src.database.models.api_keys import ApiKey
from src.database.models.usage import ModelType
from src.modules.prediction.models import ModelId
from src.modules.prediction.infrastructure.gpu_client import GPUServerClient
from src.modules.prediction.placeholders import (
    PLACEHOLDER_VEHICLE_RESULT,
    PLACEHOLDER_PROPERTY_RESULT,
)

logger = logging.getLogger(__name__)


async def predict_from_upload(
    request: Request,
    image_data: bytes,
    gpu_client: GPUServerClient,
    model_type: ModelType,
    db: AsyncSession | None = None,
    current_user: AuthenticatedUserContext | None = None,
    input_filename: str | None = None,
    save_to_db: bool = True,
    credits_consumed: int | None = None,
    model_id: ModelId | None = None,
) -> tuple[PredictionResult, UUID]:
    """
    Predict from uploaded image data via GPU server.

    Returns clustered location predictions with geographic center and radius.
    """
    start_time = time.time()
    prediction_id = uuid.uuid4()

    if not image_data:
        raise GeoInferException(
            MessageCode.IMAGE_PROCESSING_ERROR,
            status.HTTP_400_BAD_REQUEST,
            details={"description": "Empty image data provided"},
        )

    try:
        result: PredictionResult

        match model_type:
            case ModelType.GLOBAL | ModelType.ACCURACY:
                result = await gpu_client.predict_from_bytes(image_data)

            case ModelType.CARS:
                # TODO: Implement GPU support - using static placeholder
                result = PLACEHOLDER_VEHICLE_RESULT

            case ModelType.PROPERTY:
                # TODO: Implement GPU support - using static placeholder
                result = PLACEHOLDER_PROPERTY_RESULT

        processing_time_ms = int((time.time() - start_time) * 1000)

        # Save to database if requested and we have the required parameters
        # TODO: Add support for saving to database for all models
        if (
            save_to_db
            and db is not None
            and current_user is not None
            and model_type in (ModelType.GLOBAL)
        ):
            await save_prediction_to_db(
                db=db,
                prediction_id=prediction_id,
                user_id=current_user.user.id,
                organization_id=current_user.organization.id,
                api_key_id=(current_user.api_key.id if current_user.api_key else None),
                processing_time_ms=processing_time_ms,
                credits_consumed=credits_consumed,
                model_type=model_type,
                model_id=model_id.value if model_id else None,
            )

        return result, prediction_id

    except RuntimeError as e:
        # GPU server unavailable
        logger.error(f"GPU server error: {e}")
        raise GeoInferException(
            MessageCode.EXTERNAL_SERVICE_ERROR,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"description": "Prediction service temporarily unavailable"},
        )
    except Exception as e:
        logger.error(f"Error predicting from uploaded image: {e}")
        raise GeoInferException(
            MessageCode.PREDICTION_FAILED,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"description": "Prediction failed due to an internal error"},
        )


async def save_prediction_to_db(
    db: AsyncSession,
    prediction_id: UUID,
    user_id: UUID | None,
    organization_id: UUID,
    api_key_id: UUID | None,
    processing_time_ms: int | None = None,
    credits_consumed: int | None = None,
    model_type: ModelType = ModelType.GLOBAL,
    model_id: str | None = None,
) -> None:
    """Save prediction tracking to the database."""

    prediction = Prediction(
        id=prediction_id,
        user_id=user_id,
        organization_id=organization_id,
        api_key_id=api_key_id,
        processing_time_ms=processing_time_ms,
        credits_consumed=credits_consumed,
        model_type=model_type,
        model_id=model_id,
    )

    db.add(prediction)
    await db.commit()


class PredictionHistoryService(BaseService):
    """Service for retrieving prediction history with user and usage details."""

    async def get_prediction_history(
        self, organization_id: UUID, limit: int = 50, offset: int = 0
    ) -> Paginated[PredictionHistoryRecord]:
        """Get organization's prediction history with user/API key details."""

        # Build the main query with simple joins for names only
        stmt = (
            select(
                Prediction,
                User.name.label("user_name"),
                ApiKey.name.label("api_key_name"),
            )
            .outerjoin(User, Prediction.user_id == User.id)
            .outerjoin(ApiKey, Prediction.api_key_id == ApiKey.id)
            .where(Prediction.organization_id == organization_id)
            .order_by(Prediction.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        # Get total count
        count_stmt = select(func.count(Prediction.id)).where(
            Prediction.organization_id == organization_id
        )
        count_result = await self.db.execute(count_stmt)
        total_records = count_result.scalar() or 0

        # Transform to response models
        prediction_records = [
            PredictionHistoryRecord.from_prediction_row(
                prediction=row.Prediction,
                user_name=row.user_name,
                api_key_name=row.api_key_name,
            )
            for row in rows
        ]

        # Create pagination info
        pagination_info = PaginationInfo(
            total=total_records,
            limit=limit,
            offset=offset,
            has_more=offset + len(prediction_records) < total_records,
        )

        return Paginated[PredictionHistoryRecord](
            items=prediction_records,
            pagination=pagination_info,
        )
