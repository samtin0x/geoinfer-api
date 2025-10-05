"""Tests for prediction sharing endpoints."""

import io
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import orjson
import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    FeedbackType,
    Organization,
    PredictionFeedback,
    SharedPrediction,
    User,
)
from tests.factories import PredictionFactory


@pytest.fixture
def valid_prediction_result() -> dict:
    """Create a valid prediction result for testing."""
    return {
        "coordinates": {"lat": 51.5074, "lng": -0.1278},
        "confidence": 0.95,
        "location_info": {
            "city": "London",
            "country": "United Kingdom",
            "region": "England",
        },
    }


@pytest.fixture
def valid_image_data() -> bytes:
    """Create valid PNG image data for testing."""
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13"
        b"\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\nIDATx\x9cc\xf8"
        b"\x00\x00\x00\x01\x00\x01\x00\x18\xdd\x8d\xb9\x00\x00\x00\x00"
        b"IEND\xaeB`\x82"
    )


@pytest.mark.asyncio
class TestCreatePredictionShare:
    """Test POST /{prediction_id}/share endpoint."""

    async def test_create_share_success(
        self,
        app,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        test_organization: Organization,
        test_admin_user: User,
        valid_prediction_result: dict,
        valid_image_data: bytes,
    ):
        """Test successful creation of a shareable prediction link."""
        # Create a prediction in the database
        prediction = await PredictionFactory.create_async(
            db_session,
            id=uuid4(),
            user_id=test_admin_user.id,
            organization_id=test_organization.id,
            processing_time_ms=1500,
        )
        await db_session.commit()

        # Mock R2 client methods
        with (
            patch(
                "src.utils.r2_client.R2Client._generate_key",
                return_value=f"raw/organization/{test_organization.id}/test-image.jpg",
            ),
            patch(
                "src.utils.r2_client.R2Client.upload_prediction_image",
                new_callable=AsyncMock,
                return_value=f"https://r2.example.com/raw/organization/{test_organization.id}/test-image.jpg",
            ),
            patch(
                "src.utils.r2_client.R2Client.generate_signed_url",
                new_callable=AsyncMock,
                return_value="https://r2.example.com/signed-url",
            ),
        ):
            response = await admin_client.post(
                f"/v1/prediction/{prediction.id}/share",
                data={"result_data": orjson.dumps(valid_prediction_result).decode()},
                files={"file": ("test.png", io.BytesIO(valid_image_data), "image/png")},
            )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message_code"] == "share_created"
        assert "data" in data

        share_data = data["data"]
        assert str(share_data["prediction_id"]) == str(prediction.id)
        assert share_data["share_url"] == f"/shared?predictionId={prediction.id}"
        assert share_data["is_active"] is True
        assert "image_url" in share_data
        assert "result_data" in share_data
        assert share_data["result_data"]["coordinates"]["lat"] == 51.5074

    async def test_create_share_prediction_not_found(
        self,
        app,
        admin_client: AsyncClient,
        valid_prediction_result: dict,
        valid_image_data: bytes,
    ):
        """Test creating share for non-existent prediction returns 404."""
        non_existent_id = uuid4()

        response = await admin_client.post(
            f"/v1/prediction/{non_existent_id}/share",
            data={"result_data": orjson.dumps(valid_prediction_result).decode()},
            files={"file": ("test.png", io.BytesIO(valid_image_data), "image/png")},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert data["message_code"] == "not_found"

    async def test_create_share_wrong_organization(
        self,
        app,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        valid_prediction_result: dict,
        valid_image_data: bytes,
    ):
        """Test creating share for prediction from different organization returns 403."""
        # Create another organization and prediction
        other_org_id = uuid4()
        prediction = await PredictionFactory.create_async(
            db_session,
            id=uuid4(),
            user_id=uuid4(),
            organization_id=other_org_id,
            processing_time_ms=1500,
        )
        await db_session.commit()

        response = await admin_client.post(
            f"/v1/prediction/{prediction.id}/share",
            data={"result_data": orjson.dumps(valid_prediction_result).decode()},
            files={"file": ("test.png", io.BytesIO(valid_image_data), "image/png")},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_create_share_already_exists(
        self,
        app,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        test_organization: Organization,
        test_admin_user: User,
        valid_prediction_result: dict,
        valid_image_data: bytes,
    ):
        """Test creating share for already shared prediction returns existing share."""
        # Create prediction and existing share
        prediction = await PredictionFactory.create_async(
            db_session,
            id=uuid4(),
            user_id=test_admin_user.id,
            organization_id=test_organization.id,
            processing_time_ms=1500,
        )
        existing_share = SharedPrediction(
            prediction_id=prediction.id,
            result_data=valid_prediction_result,
            image_key=f"raw/organization/{test_organization.id}/existing-image.jpg",
            is_active=True,
        )
        db_session.add(existing_share)
        await db_session.commit()

        with patch(
            "src.utils.r2_client.R2Client.generate_signed_url",
            new_callable=AsyncMock,
            return_value="https://r2.example.com/signed-url",
        ):
            response = await admin_client.post(
                f"/v1/prediction/{prediction.id}/share",
                data={"result_data": orjson.dumps(valid_prediction_result).decode()},
                files={"file": ("test.png", io.BytesIO(valid_image_data), "image/png")},
            )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert str(data["data"]["prediction_id"]) == str(prediction.id)

    async def test_create_share_invalid_json_in_result_data(
        self,
        app,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        test_organization: Organization,
        test_admin_user: User,
        valid_image_data: bytes,
    ):
        """Test creating share with invalid JSON in result_data returns 400."""
        prediction = await PredictionFactory.create_async(
            db_session,
            id=uuid4(),
            user_id=test_admin_user.id,
            organization_id=test_organization.id,
            processing_time_ms=1500,
        )
        await db_session.commit()

        response = await admin_client.post(
            f"/v1/prediction/{prediction.id}/share",
            data={"result_data": "invalid json data"},
            files={"file": ("test.png", io.BytesIO(valid_image_data), "image/png")},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_create_share_invalid_image_file(
        self,
        app,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        test_organization: Organization,
        test_admin_user: User,
        valid_prediction_result: dict,
    ):
        """Test creating share with invalid image file returns 400."""
        prediction = await PredictionFactory.create_async(
            db_session,
            id=uuid4(),
            user_id=test_admin_user.id,
            organization_id=test_organization.id,
            processing_time_ms=1500,
        )
        await db_session.commit()

        response = await admin_client.post(
            f"/v1/prediction/{prediction.id}/share",
            data={"result_data": orjson.dumps(valid_prediction_result).decode()},
            files={"file": ("test.txt", io.BytesIO(b"not an image"), "text/plain")},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_create_share_image_too_large(
        self,
        app,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        test_organization: Organization,
        test_admin_user: User,
        valid_prediction_result: dict,
    ):
        """Test creating share with image too large returns 400."""
        prediction = await PredictionFactory.create_async(
            db_session,
            id=uuid4(),
            user_id=test_admin_user.id,
            organization_id=test_organization.id,
            processing_time_ms=1500,
        )
        await db_session.commit()

        # Create 11MB image (exceeds 10MB limit)
        large_image = b"x" * (11 * 1024 * 1024)

        response = await admin_client.post(
            f"/v1/prediction/{prediction.id}/share",
            data={"result_data": orjson.dumps(valid_prediction_result).decode()},
            files={"file": ("large.jpg", io.BytesIO(large_image), "image/jpeg")},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_create_share_requires_authentication(
        self,
        app,
        public_client: AsyncClient,
        db_session: AsyncSession,
        valid_prediction_result: dict,
        valid_image_data: bytes,
    ):
        """Test creating share without authentication returns 401."""
        prediction_id = uuid4()

        response = await public_client.post(
            f"/v1/prediction/{prediction_id}/share",
            data={"result_data": orjson.dumps(valid_prediction_result).decode()},
            files={"file": ("test.png", io.BytesIO(valid_image_data), "image/png")},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_create_share_r2_upload_failure(
        self,
        app,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        test_organization: Organization,
        test_admin_user: User,
        valid_prediction_result: dict,
        valid_image_data: bytes,
    ):
        """Test creating share when R2 upload fails returns 503."""
        prediction = await PredictionFactory.create_async(
            db_session,
            id=uuid4(),
            user_id=test_admin_user.id,
            organization_id=test_organization.id,
            processing_time_ms=1500,
        )
        await db_session.commit()

        # Mock R2 upload to fail
        with (
            patch(
                "src.utils.r2_client.R2Client._generate_key",
                return_value=f"raw/organization/{test_organization.id}/test-image.jpg",
            ),
            patch(
                "src.utils.r2_client.R2Client.upload_prediction_image",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            response = await admin_client.post(
                f"/v1/prediction/{prediction.id}/share",
                data={"result_data": orjson.dumps(valid_prediction_result).decode()},
                files={"file": ("test.png", io.BytesIO(valid_image_data), "image/png")},
            )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.asyncio
class TestGetSharedPrediction:
    """Test GET /{prediction_id}/share endpoint."""

    async def test_get_shared_prediction_success(
        self,
        app,
        public_client: AsyncClient,
        db_session: AsyncSession,
        test_organization: Organization,
        test_admin_user: User,
        valid_prediction_result: dict,
    ):
        """Test successfully retrieving a shared prediction."""
        # Create prediction and share
        prediction = await PredictionFactory.create_async(
            db_session,
            id=uuid4(),
            user_id=test_admin_user.id,
            organization_id=test_organization.id,
            processing_time_ms=1500,
        )
        shared = SharedPrediction(
            prediction_id=prediction.id,
            result_data=valid_prediction_result,
            image_key=f"raw/organization/{test_organization.id}/test-image.jpg",
            is_active=True,
        )
        db_session.add(shared)
        await db_session.commit()

        with patch(
            "src.utils.r2_client.R2Client.generate_signed_url",
            new_callable=AsyncMock,
            return_value="https://r2.example.com/signed-url",
        ):
            response = await public_client.get(f"/v1/prediction/{prediction.id}/share")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message_code"] == "success"
        assert "data" in data

        share_data = data["data"]
        assert str(share_data["prediction_id"]) == str(prediction.id)
        assert share_data["is_active"] is True
        assert share_data["image_url"] == "https://r2.example.com/signed-url"
        assert "result_data" in share_data

    async def test_get_shared_prediction_not_found(
        self, app, public_client: AsyncClient
    ):
        """Test getting non-existent shared prediction returns 404."""
        non_existent_id = uuid4()

        response = await public_client.get(f"/v1/prediction/{non_existent_id}/share")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_get_shared_prediction_inactive(
        self,
        app,
        public_client: AsyncClient,
        db_session: AsyncSession,
        test_organization: Organization,
        test_admin_user: User,
        valid_prediction_result: dict,
    ):
        """Test getting inactive shared prediction returns 404."""
        # Create prediction and inactive share
        prediction = await PredictionFactory.create_async(
            db_session,
            id=uuid4(),
            user_id=test_admin_user.id,
            organization_id=test_organization.id,
            processing_time_ms=1500,
        )
        shared = SharedPrediction(
            prediction_id=prediction.id,
            result_data=valid_prediction_result,
            image_key=f"raw/organization/{test_organization.id}/test-image.jpg",
            is_active=False,
        )
        db_session.add(shared)
        await db_session.commit()

        response = await public_client.get(f"/v1/prediction/{prediction.id}/share")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_get_shared_prediction_r2_url_generation_fails(
        self,
        app,
        public_client: AsyncClient,
        db_session: AsyncSession,
        test_organization: Organization,
        test_admin_user: User,
        valid_prediction_result: dict,
    ):
        """Test getting shared prediction when R2 URL generation fails returns 503."""
        prediction = await PredictionFactory.create_async(
            db_session,
            id=uuid4(),
            user_id=test_admin_user.id,
            organization_id=test_organization.id,
            processing_time_ms=1500,
        )
        shared = SharedPrediction(
            prediction_id=prediction.id,
            result_data=valid_prediction_result,
            image_key=f"raw/organization/{test_organization.id}/test-image.jpg",
            is_active=True,
        )
        db_session.add(shared)
        await db_session.commit()

        with patch(
            "src.utils.r2_client.R2Client.generate_signed_url",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await public_client.get(f"/v1/prediction/{prediction.id}/share")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.asyncio
class TestAddPredictionFeedback:
    """Test POST /{prediction_id}/feedback endpoint."""

    async def test_add_feedback_success(
        self,
        app,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        test_prediction,
    ):
        """Test successfully adding feedback to a prediction."""
        response = await admin_client.post(
            f"/v1/prediction/{test_prediction.id}/feedback",
            json={
                "feedback": "correct",
                "comment": "The prediction was accurate!",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message_code"] == "feedback_added"
        assert data["data"] is True

        # Verify feedback was created in database
        feedback = await db_session.get(PredictionFeedback, test_prediction.id)
        assert feedback is not None
        assert feedback.feedback == FeedbackType.CORRECT
        assert feedback.comment == "The prediction was accurate!"

    async def test_add_feedback_updates_existing(
        self,
        app,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        test_prediction,
    ):
        """Test updating existing feedback for a prediction."""
        # Create existing feedback
        existing_feedback = PredictionFeedback(
            prediction_id=test_prediction.id,
            feedback=FeedbackType.INCORRECT,
            comment="Initial feedback",
        )
        db_session.add(existing_feedback)
        await db_session.commit()

        response = await admin_client.post(
            f"/v1/prediction/{test_prediction.id}/feedback",
            json={
                "feedback": "correct",
                "comment": "Actually it was correct!",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["data"] is True

        # Verify feedback was updated
        await db_session.refresh(existing_feedback)
        assert existing_feedback.feedback == FeedbackType.CORRECT
        assert existing_feedback.comment == "Actually it was correct!"

    async def test_add_feedback_prediction_not_found(
        self, app, admin_client: AsyncClient
    ):
        """Test adding feedback to non-existent prediction returns 404."""
        non_existent_id = uuid4()

        response = await admin_client.post(
            f"/v1/prediction/{non_existent_id}/feedback",
            json={"feedback": "correct", "comment": "Test"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_add_feedback_without_comment(
        self,
        app,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        test_prediction,
    ):
        """Test adding feedback without optional comment."""
        response = await admin_client.post(
            f"/v1/prediction/{test_prediction.id}/feedback",
            json={"feedback": "close"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["data"] is True

        # Verify feedback was created without comment
        feedback = await db_session.get(PredictionFeedback, test_prediction.id)
        assert feedback is not None
        assert feedback.feedback == FeedbackType.CLOSE
        assert feedback.comment is None

    @pytest.mark.parametrize(
        "feedback_type",
        ["correct", "incorrect", "close"],
    )
    async def test_add_feedback_all_types(
        self,
        app,
        admin_client: AsyncClient,
        test_prediction,
        feedback_type: str,
    ):
        """Test adding feedback with all valid feedback types."""
        response = await admin_client.post(
            f"/v1/prediction/{test_prediction.id}/feedback",
            json={"feedback": feedback_type, "comment": f"Test {feedback_type}"},
        )

        assert response.status_code == status.HTTP_200_OK

    async def test_add_feedback_invalid_type(
        self,
        app,
        admin_client: AsyncClient,
        test_prediction,
    ):
        """Test adding feedback with invalid type returns 400."""
        response = await admin_client.post(
            f"/v1/prediction/{test_prediction.id}/feedback",
            json={"feedback": "invalid_type", "comment": "Test"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_add_feedback_requires_authentication(
        self, app, public_client: AsyncClient
    ):
        """Test adding feedback without authentication returns 401."""
        prediction_id = uuid4()

        response = await public_client.post(
            f"/v1/prediction/{prediction_id}/feedback",
            json={"feedback": "correct", "comment": "Test"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
class TestRevokePredictionShare:
    """Test DELETE /{prediction_id}/share endpoint."""

    async def test_revoke_share_success(
        self,
        app,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        test_organization: Organization,
        test_admin_user: User,
        valid_prediction_result: dict,
    ):
        """Test successfully revoking a shared prediction."""
        # Create prediction and share
        prediction = await PredictionFactory.create_async(
            db_session,
            id=uuid4(),
            user_id=test_admin_user.id,
            organization_id=test_organization.id,
            processing_time_ms=1500,
        )
        shared = SharedPrediction(
            prediction_id=prediction.id,
            result_data=valid_prediction_result,
            image_key=f"raw/organization/{test_organization.id}/test-image.jpg",
            is_active=True,
        )
        db_session.add(shared)
        await db_session.commit()

        response = await admin_client.delete(f"/v1/prediction/{prediction.id}/share")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message_code"] == "share_revoked"

        # Verify share is now inactive
        await db_session.refresh(shared)
        assert shared.is_active is False

    async def test_revoke_share_not_found(
        self, app, admin_client: AsyncClient, db_session: AsyncSession
    ):
        """Test revoking non-existent share returns 404."""
        non_existent_id = uuid4()

        response = await admin_client.delete(f"/v1/prediction/{non_existent_id}/share")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_revoke_share_wrong_organization(
        self,
        app,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        valid_prediction_result: dict,
    ):
        """Test revoking share for prediction from different organization returns 403."""
        # Create prediction from different organization
        other_org_id = uuid4()
        prediction = await PredictionFactory.create_async(
            db_session,
            id=uuid4(),
            user_id=uuid4(),
            organization_id=other_org_id,
            processing_time_ms=1500,
        )
        shared = SharedPrediction(
            prediction_id=prediction.id,
            result_data=valid_prediction_result,
            image_key=f"raw/organization/{other_org_id}/test-image.jpg",
            is_active=True,
        )
        db_session.add(shared)
        await db_session.commit()

        response = await admin_client.delete(f"/v1/prediction/{prediction.id}/share")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_revoke_share_already_inactive(
        self,
        app,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        test_organization: Organization,
        test_admin_user: User,
        valid_prediction_result: dict,
    ):
        """Test revoking already inactive share still succeeds."""
        # Create prediction and inactive share
        prediction = await PredictionFactory.create_async(
            db_session,
            id=uuid4(),
            user_id=test_admin_user.id,
            organization_id=test_organization.id,
            processing_time_ms=1500,
        )
        shared = SharedPrediction(
            prediction_id=prediction.id,
            result_data=valid_prediction_result,
            image_key=f"raw/organization/{test_organization.id}/test-image.jpg",
            is_active=False,
        )
        db_session.add(shared)
        await db_session.commit()

        response = await admin_client.delete(f"/v1/prediction/{prediction.id}/share")

        assert response.status_code == status.HTTP_200_OK

    async def test_revoke_share_requires_authentication(
        self,
        app,
        public_client: AsyncClient,
    ):
        """Test revoking share without authentication returns 401."""
        prediction_id = uuid4()

        response = await public_client.delete(f"/v1/prediction/{prediction_id}/share")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
