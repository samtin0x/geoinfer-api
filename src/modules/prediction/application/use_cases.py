import logging
import time
import uuid
from uuid import UUID

import numpy as np
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
from src.database.models.usage import UsageType
from src.modules.prediction.infrastructure.gpu_client import GPUServerClient

logger = logging.getLogger(__name__)


async def predict_coordinates_from_upload(
    request: Request,
    image_data: bytes,
    gpu_client: GPUServerClient,
    top_k: int = 5,
    db: AsyncSession | None = None,
    current_user: AuthenticatedUserContext | None = None,
    input_filename: str | None = None,
    save_to_db: bool = True,
    credits_consumed: int | None = None,
    usage_type: UsageType | None = None,
) -> PredictionResult:
    """
    Predict GPS coordinates from uploaded image data via GPU server.

    Args:
        request: FastAPI request object
        image_data: Image bytes to process
        gpu_client: GPU server client instance
        top_k: Number of top predictions to return
        db: Database session (required if save_to_db=True)
        current_user: Current authenticated user (required if save_to_db=True)
        input_filename: Filename for the uploaded file
        save_to_db: Whether to save prediction to database

    Returns:
        PredictionResult with multiple predictions and timing info
    """
    start_time = time.time()

    # Validate image data
    if not image_data:
        raise GeoInferException(
            MessageCode.IMAGE_PROCESSING_ERROR,
            status.HTTP_400_BAD_REQUEST,
            details={"description": "Empty image data provided"},
        )

    try:
        # Call GPU server for prediction
        result = await gpu_client.predict_from_bytes(image_data, top_k=top_k)

        processing_time_ms = int((time.time() - start_time) * 1000)

        # Save to database if requested and we have the required parameters
        if save_to_db and db is not None and current_user is not None:
            await save_prediction_to_db(
                db=db,
                user_id=current_user.user.id,
                organization_id=current_user.organization.id,
                api_key_id=(current_user.api_key.id if current_user.api_key else None),
                processing_time_ms=processing_time_ms,
                credits_consumed=credits_consumed,
                usage_type=usage_type or UsageType.GEOINFER_GLOBAL_0_0_1,
            )

        return result

    except RuntimeError as e:
        # GPU server unavailable
        logger.error(f"GPU server error: {e}")
        raise GeoInferException(
            MessageCode.EXTERNAL_SERVICE_ERROR,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"description": "Prediction service temporarily unavailable"},
        )
    except Exception as e:
        logger.error(f"Error predicting coordinates from uploaded image: {e}")
        raise GeoInferException(
            MessageCode.PREDICTION_FAILED,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"description": "Prediction failed due to an internal error"},
        )


async def save_prediction_to_db(
    db: AsyncSession,
    user_id: UUID | None,
    organization_id: UUID,
    api_key_id: UUID | None,
    processing_time_ms: int | None = None,
    credits_consumed: int | None = None,
    usage_type: UsageType = UsageType.GEOINFER_GLOBAL_0_0_1,
) -> Prediction:
    """Save prediction tracking to the database."""

    prediction = Prediction(
        id=uuid.uuid4(),
        user_id=user_id,
        organization_id=organization_id,
        api_key_id=api_key_id,
        processing_time_ms=processing_time_ms,
        credits_consumed=credits_consumed,
        usage_type=usage_type,
    )

    db.add(prediction)
    await db.commit()
    await db.refresh(prediction)

    return prediction


def calculate_haversine_distance(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Calculate the Haversine distance between two points in kilometers."""
    rad_np = np.float64(6378137.0)  # Radius of the Earth (in meters)

    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    c = 2 * np.arcsin(np.sqrt(a))
    km = (rad_np * c) / 1000
    return float(km)


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
