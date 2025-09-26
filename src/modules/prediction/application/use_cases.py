import asyncio
import logging
import os
import tempfile
import time
from io import BytesIO
from uuid import UUID

import aiohttp
import numpy as np
import torch
from fastapi import Request, status
from PIL import Image, UnidentifiedImageError
import pillow_heif  # type: ignore
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode, Paginated, PaginationInfo
from src.core.context import AuthenticatedUserContext
from src.api.prediction.schemas import (
    CoordinatePrediction,
    PredictionResult,
    PredictionHistoryRecord,
)
from src.core.base import BaseService
from src.database.models.predictions import Prediction
from src.database.models.users import User
from src.database.models.api_keys import ApiKey
from src.database.models.usage import UsageType
import uuid
from src.modules.prediction.infrastructure.inference import (
    get_model,
    normalize_confidences,
    get_location_info,
)

logger = logging.getLogger(__name__)

pillow_heif.register_heif_opener()

torch.set_num_threads(torch.get_num_threads())


async def download_image(image_url: str) -> Image.Image:
    """Download and open an image from a URL."""
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as response:
            if response.status != 200:
                raise GeoInferException(
                    MessageCode.EXTERNAL_SERVICE_ERROR,
                    status.HTTP_400_BAD_REQUEST,
                    details={
                        "description": f"Failed to download image: HTTP {response.status}"
                    },
                )

            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                raise GeoInferException(
                    MessageCode.INVALID_FILE_TYPE,
                    status.HTTP_400_BAD_REQUEST,
                    details={"description": f"Invalid content type: {content_type}"},
                )

            image_data = await response.read()

            try:
                image = Image.open(BytesIO(image_data))
            except UnidentifiedImageError as e:
                logger.error(f"Cannot identify downloaded image format: {e}")
                raise GeoInferException(
                    MessageCode.IMAGE_PROCESSING_ERROR,
                    status.HTTP_400_BAD_REQUEST,
                    details={
                        "description": "Cannot identify image format from URL. Please ensure the URL points to a valid image file."
                    },
                )

            # Convert to RGB if necessary
            if image.mode != "RGB":
                image = image.convert("RGB")

            return image


async def predict_coordinates_from_url(
    image_url: str, top_k: int = 5
) -> PredictionResult:
    """
    Predict GPS coordinates from an image URL.

    Returns:
        PredictionResult with multiple predictions and timing info
    """
    start_time = time.time()

    try:
        # Download image
        image = await download_image(image_url)

        # Save to temporary file for GeoCLIP (it expects file paths)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
            image.save(temp_file, format="JPEG")
            temp_path = temp_file.name

        try:
            # Run prediction in thread pool to avoid blocking
            loop = asyncio.get_event_loop()

            # Get the model using lazy loading
            model = get_model()

            gps_predictions, probabilities = await loop.run_in_executor(
                None, model.predict, temp_path, top_k
            )

            # Normalize raw scores to probabilities using softmax
            raw_scores = [float(prob) for prob in probabilities]
            normalized_probs = normalize_confidences(raw_scores)

            # Convert to our format
            predictions = []
            for i, (coords, norm_prob) in enumerate(
                zip(gps_predictions, normalized_probs)
            ):
                lat, lon = coords
                location = get_location_info(float(lat), float(lon))
                predictions.append(
                    CoordinatePrediction(
                        latitude=float(lat),
                        longitude=float(lon),
                        confidence=norm_prob,
                        rank=i + 1,
                        location=location,
                    )
                )

            processing_time_ms = int((time.time() - start_time) * 1000)

            # Create result with top prediction for convenience
            return PredictionResult(
                predictions=predictions,
                processing_time_ms=processing_time_ms,
                top_prediction=predictions[0] if predictions else None,
            )

        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    except Exception as e:
        logger.error(f"Error predicting coordinates from URL {image_url}: {e}")
        raise


async def predict_coordinates_from_file(
    request: Request, image_path: str, top_k: int = 5
) -> PredictionResult:
    """
    Predict GPS coordinates from a local image file.

    Returns:
        PredictionResult with multiple predictions and timing info
    """
    start_time = time.time()

    try:
        loop = asyncio.get_event_loop()

        # Get the model using lazy loading
        model = get_model()

        gps_predictions, probabilities = await loop.run_in_executor(
            None, model.predict, image_path, top_k
        )

        # Convert to our format
        predictions = []
        for i, (coords, prob) in enumerate(zip(gps_predictions, probabilities)):
            lat, lon = coords
            predictions.append(
                CoordinatePrediction(
                    latitude=float(lat),
                    longitude=float(lon),
                    confidence=float(prob),
                    rank=i + 1,
                )
            )

        processing_time_ms = int((time.time() - start_time) * 1000)

        return PredictionResult(
            predictions=predictions,
            processing_time_ms=processing_time_ms,
            top_prediction=predictions[0] if predictions else None,
        )

    except Exception as e:
        logger.error(f"Error predicting coordinates from file {image_path}: {e}")
        raise


async def predict_coordinates_from_upload(
    request: Request,
    image_data: bytes,
    top_k: int = 5,
    db: AsyncSession | None = None,
    current_user: AuthenticatedUserContext | None = None,
    input_filename: str | None = None,
    save_to_db: bool = True,
    credits_consumed: int | None = None,
    usage_type: UsageType | None = None,
) -> PredictionResult:
    """
    Predict GPS coordinates from uploaded image data.

    Args:
        request: FastAPI request object
        image_data: Image bytes to process
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
        # Convert bytes to PIL Image
        image_io = BytesIO(image_data)
        image = Image.open(image_io)

        # Convert to RGB if necessary
        if image.mode != "RGB":
            image = image.convert("RGB")

        # Save to temporary file for GeoCLIP
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
            image.save(temp_file, format="JPEG")
            temp_path = temp_file.name

        try:
            # Run prediction in thread pool to avoid blocking
            loop = asyncio.get_event_loop()

            # Get the model using lazy loading
            model = get_model()

            gps_predictions, probabilities = await loop.run_in_executor(
                None, model.predict, temp_path, top_k
            )

            # Normalize raw scores to probabilities using softmax
            raw_scores = [float(prob) for prob in probabilities]
            normalized_probs = normalize_confidences(raw_scores)

            # Convert to our format
            predictions = []
            for i, (coords, norm_prob) in enumerate(
                zip(gps_predictions, normalized_probs)
            ):
                lat, lon = coords
                location = get_location_info(float(lat), float(lon))
                predictions.append(
                    CoordinatePrediction(
                        latitude=float(lat),
                        longitude=float(lon),
                        confidence=norm_prob,
                        rank=i + 1,
                        location=location,
                    )
                )

            processing_time_ms = int((time.time() - start_time) * 1000)

            result = PredictionResult(
                predictions=predictions,
                processing_time_ms=processing_time_ms,
                top_prediction=predictions[0] if predictions else None,
            )

            # Save to database if requested and we have the required parameters
            if save_to_db and db is not None and current_user is not None:
                await save_prediction_to_db(
                    db=db,
                    user_id=current_user.user.id,
                    organization_id=current_user.organization.id,
                    api_key_id=(
                        current_user.api_key.id if current_user.api_key else None
                    ),
                    processing_time_ms=processing_time_ms,
                    credits_consumed=credits_consumed,
                    usage_type=usage_type or UsageType.GEOINFER_GLOBAL_0_0_1,
                )

            return result

        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    except UnidentifiedImageError as e:
        logger.error(f"Cannot identify image format: {e}")
        raise GeoInferException(
            MessageCode.IMAGE_PROCESSING_ERROR,
            status.HTTP_400_BAD_REQUEST,
            details={
                "description": "Cannot identify image format. Please ensure you're uploading a valid image file (JPEG, PNG, etc.)"
            },
        )
    except (OSError, IOError) as e:
        # Handle PIL image processing errors (corrupted files, truncated files, etc.)
        logger.error(f"Image processing error: {e}")
        raise GeoInferException(
            MessageCode.IMAGE_PROCESSING_ERROR,
            status.HTTP_400_BAD_REQUEST,
            details={
                "description": "Error processing image file. The image may be corrupted or in an unsupported format."
            },
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
