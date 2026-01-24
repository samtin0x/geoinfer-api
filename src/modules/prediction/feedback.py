"""Prediction sharing service."""

from uuid import UUID

import orjson
from fastapi import status, UploadFile
from sqlalchemy import select

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.api.prediction.schemas import (
    CoordinatePrediction,
    CoordinatePredictionResult,
    parse_prediction_result,
)
from src.modules.prediction.models import ModelId
from src.api.prediction.validators import validate_image_upload
from src.core.base import BaseService
from src.core.context import AuthenticatedUserContext
from src.database.models.predictions import Prediction
from src.database.models.shared import SharedPrediction
from src.database.models.feedback import PredictionFeedback, FeedbackType
from src.database.models.usage import ModelType
from src.utils.r2_client import R2Client
from src.utils.path_helpers import build_r2_image_metadata


class SharingService(BaseService):
    """Service for managing shared predictions and feedback."""

    async def create_share(
        self,
        prediction_id: UUID,
        result_data_json: str,
        file: UploadFile,
        r2_client: R2Client,
        user: AuthenticatedUserContext,
    ) -> SharedPrediction:
        """Create a shareable prediction with full validation and upload."""

        # Verify prediction exists and user owns it
        stmt = select(Prediction).where(Prediction.id == prediction_id)
        result = await self.db.execute(stmt)
        prediction = result.scalar_one_or_none()

        if not prediction:
            raise GeoInferException(MessageCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)

        if prediction.organization_id != user.organization.id:
            raise GeoInferException(
                MessageCode.INSUFFICIENT_PERMISSIONS, status.HTTP_403_FORBIDDEN
            )

        # Check if already shared
        stmt = select(SharedPrediction).where(
            SharedPrediction.prediction_id == prediction_id
        )
        result = await self.db.execute(stmt)
        existing_share = result.scalar_one_or_none()

        if existing_share:
            return existing_share

        # Parse and validate result data using TypeAdapter for Union types
        result_dict = orjson.loads(result_data_json)
        prediction_result = parse_prediction_result(result_dict)

        # Extract top prediction for metadata (only coordinate results have lat/lng)
        top_pred: CoordinatePrediction | None = None
        if isinstance(prediction_result, CoordinatePredictionResult):
            if prediction_result.predictions:
                top_pred = prediction_result.predictions[0]

        # Validate and upload image
        file_content = await validate_image_upload(file, 10 * 1024 * 1024)

        # Generate key and upload to R2 with prediction metadata
        image_key = r2_client._generate_key(
            organization_id=user.organization.id,
            filename=file.filename or "image.bin",
            prediction_id=prediction_id,
        )

        # model_id and model_type are guaranteed by migration (defaults to global_v0.1/global)
        assert prediction.model_id is not None
        assert prediction.model_type is not None

        await r2_client.upload_prediction_image(
            image_data=file_content,
            organization_id=user.organization.id,
            filename=file.filename or "image.bin",
            prediction_id=prediction_id,
            ip_address=None,
            extra_metadata=build_r2_image_metadata(
                top_prediction=top_pred,
                prediction_id=prediction_id,
                model_id=ModelId(prediction.model_id),
                model_type=ModelType(prediction.model_type),
            ),
        )

        # Create share record
        shared_prediction = SharedPrediction(
            prediction_id=prediction_id,
            result_data=prediction_result.model_dump(),
            image_key=image_key,
            is_active=True,
        )

        self.db.add(shared_prediction)
        await self.db.commit()
        await self.db.refresh(shared_prediction)

        return shared_prediction

    async def get_shared_prediction(
        self, prediction_id: UUID
    ) -> SharedPrediction | None:
        """Get a shared prediction by prediction_id."""

        stmt = select(SharedPrediction).where(
            SharedPrediction.prediction_id == prediction_id,
            SharedPrediction.is_active,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def add_feedback(
        self,
        prediction_id: UUID,
        feedback: FeedbackType,
        comment: str | None = None,
    ) -> PredictionFeedback:
        """Add or update feedback for a prediction."""

        stmt = select(Prediction).where(Prediction.id == prediction_id)
        result = await self.db.execute(stmt)
        prediction = result.scalar_one_or_none()

        if not prediction:
            raise GeoInferException(MessageCode.NOT_FOUND, 404)

        stmt = select(PredictionFeedback).where(
            PredictionFeedback.prediction_id == prediction_id
        )
        result = await self.db.execute(stmt)
        existing_feedback = result.scalar_one_or_none()

        if existing_feedback:
            existing_feedback.feedback = feedback
            existing_feedback.comment = comment
            await self.db.commit()
            await self.db.refresh(existing_feedback)
            return existing_feedback

        prediction_feedback = PredictionFeedback(
            prediction_id=prediction_id,
            feedback=feedback,
            comment=comment,
        )

        self.db.add(prediction_feedback)
        await self.db.commit()
        await self.db.refresh(prediction_feedback)

        return prediction_feedback

    async def revoke_share(
        self, prediction_id: UUID, user: AuthenticatedUserContext
    ) -> bool:
        """Revoke/disable a share."""

        stmt = select(SharedPrediction).where(
            SharedPrediction.prediction_id == prediction_id
        )
        result = await self.db.execute(stmt)
        shared = result.scalar_one_or_none()

        if not shared:
            return False

        prediction = await self.db.get(Prediction, prediction_id)
        if not prediction or prediction.organization_id != user.organization.id:
            raise GeoInferException(MessageCode.INSUFFICIENT_PERMISSIONS, 403)

        shared.is_active = False
        await self.db.commit()

        return True
