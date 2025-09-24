"""Comprehensive tests for prediction functionality - both business logic and API."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4
from unittest.mock import patch

from src.database.models import User, Organization
from src.api.core.messages import MessageCode
from tests.utils.assertions import (
    assert_success_response,
    assert_error_response,
    assert_not_found_error,
    assert_validation_error,
)


class TestPredictionBusinessLogic:
    """Test the core prediction business logic functions."""

    @pytest.mark.asyncio
    async def test_prediction_creation_with_factory(
        self,
        db_session: AsyncSession,
        prediction_factory,
        test_user: User,
        test_organization: Organization,
    ):
        """Test creating a prediction using the factory system."""
        prediction = await prediction_factory.create_async(
            db_session,
            user_id=test_user.id,
            organization_id=test_organization.id,
            input_type="url",
            input_data="https://example.com/image.jpg",
            prediction_result='{"lat": 37.7749, "lng": -122.4194, "confidence": 0.85}',
            status="completed",
        )

        # Assertions
        assert prediction.user_id == test_user.id
        assert prediction.organization_id == test_organization.id
        assert prediction.input_type == "url"
        assert prediction.input_data == "https://example.com/image.jpg"
        assert prediction.status == "completed"
        assert prediction.id is not None
        assert prediction.created_at is not None

    @pytest.mark.asyncio
    async def test_prediction_status_types(
        self, db_session: AsyncSession, prediction_factory, test_user: User
    ):
        """Test different prediction status types."""
        # Create predictions with different statuses
        completed = await prediction_factory.create_async(
            db_session,
            user_id=test_user.id,
            status="completed",
            prediction_result='{"lat": 37.7749, "lng": -122.4194}',
        )

        failed = await prediction_factory.create_async(
            db_session,
            user_id=test_user.id,
            status="failed",
            error_message="Image processing failed",
        )

        processing = await prediction_factory.create_async(
            db_session, user_id=test_user.id, status="processing"
        )

        assert completed.status == "completed"
        assert completed.prediction_result is not None
        assert failed.status == "failed"
        assert failed.error_message == "Image processing failed"
        assert processing.status == "processing"

    @pytest.mark.asyncio
    async def test_prediction_input_types(
        self, db_session: AsyncSession, prediction_factory, test_user: User
    ):
        """Test different prediction input types."""
        # URL input
        url_prediction = await prediction_factory.create_async(
            db_session,
            user_id=test_user.id,
            input_type="url",
            input_data="https://example.com/image.jpg",
        )

        # Upload input
        upload_prediction = await prediction_factory.create_async(
            db_session,
            user_id=test_user.id,
            input_type="upload",
            input_data="/tmp/uploads/image_12345.jpg",
        )

        assert url_prediction.input_type == "url"
        assert url_prediction.input_data.startswith("https://")
        assert upload_prediction.input_type == "upload"
        assert upload_prediction.input_data.startswith("/")


class TestPredictionAPIEndpoints:
    """Test prediction API endpoints with proper authentication and permissions."""

    @pytest.mark.asyncio
    async def test_create_prediction_from_url_success(
        self, authorized_client: AsyncClient, test_user: User
    ):
        """Test creating a prediction from URL successfully."""
        prediction_data = {
            "input_type": "url",
            "input_data": "https://example.com/test-image.jpg",
        }

        # Mock the actual prediction service
        with patch(
            "src.modules.prediction.application.use_cases.PredictionService.predict_from_url"
        ) as mock_predict:
            mock_predict.return_value = {
                "latitude": 37.7749,
                "longitude": -122.4194,
                "confidence": 0.85,
                "processing_time_ms": 1500,
            }

            response = await authorized_client.post(
                "/api/v1/predictions", json=prediction_data
            )

        # Assert successful creation
        data = assert_success_response(response, MessageCode.CREATED, 201)

        # Verify prediction data
        assert data["input_type"] == "url"
        assert data["input_data"] == "https://example.com/test-image.jpg"
        assert data["status"] == "completed"
        assert "prediction_result" in data
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_prediction_with_api_key(self, api_key_client: AsyncClient):
        """Test creating prediction using API key authentication."""
        prediction_data = {
            "input_type": "url",
            "input_data": "https://example.com/api-test-image.jpg",
        }

        with patch(
            "src.modules.prediction.application.use_cases.PredictionService.predict_from_url"
        ) as mock_predict:
            mock_predict.return_value = {
                "latitude": 40.7128,
                "longitude": -74.0060,
                "confidence": 0.92,
            }

            response = await api_key_client.post(
                "/api/v1/predictions", json=prediction_data
            )

        # Should succeed with API key
        assert_success_response(response, MessageCode.CREATED, 201)

    @pytest.mark.asyncio
    async def test_create_prediction_unauthenticated(self, public_client: AsyncClient):
        """Test creating prediction without authentication."""
        prediction_data = {
            "input_type": "url",
            "input_data": "https://example.com/test-image.jpg",
        }

        response = await public_client.post("/api/v1/predictions", json=prediction_data)

        # Should require authentication
        assert_error_response(response, MessageCode.UNAUTHORIZED, 401)

    @pytest.mark.asyncio
    async def test_list_predictions_success(
        self,
        authorized_client: AsyncClient,
        db_session: AsyncSession,
        prediction_factory,
        test_user: User,
    ):
        """Test listing user's predictions."""
        # Create some predictions for the user
        prediction1 = await prediction_factory.create_async(
            db_session,
            user_id=test_user.id,
            input_type="url",
            input_data="https://example.com/image1.jpg",
        )

        prediction2 = await prediction_factory.create_async(
            db_session,
            user_id=test_user.id,
            input_type="upload",
            input_data="/tmp/image2.jpg",
        )

        response = await authorized_client.get("/api/v1/predictions")

        # Assert successful response
        data = assert_success_response(response, MessageCode.SUCCESS, 200)

        # Should return list of predictions
        assert isinstance(data, list)
        assert len(data) >= 2

        # Find our test predictions
        prediction_ids = [pred["id"] for pred in data]
        assert str(prediction1.id) in prediction_ids
        assert str(prediction2.id) in prediction_ids

    @pytest.mark.asyncio
    async def test_get_prediction_by_id_success(
        self,
        authorized_client: AsyncClient,
        db_session: AsyncSession,
        prediction_factory,
        test_user: User,
    ):
        """Test getting a specific prediction by ID."""
        prediction = await prediction_factory.create_async(
            db_session,
            user_id=test_user.id,
            input_type="url",
            input_data="https://example.com/specific-image.jpg",
            prediction_result='{"lat": 51.5074, "lng": -0.1278}',
            status="completed",
        )

        response = await authorized_client.get(f"/api/v1/predictions/{prediction.id}")

        # Assert successful response
        data = assert_success_response(
            response,
            MessageCode.SUCCESS,
            200,
            {"id": str(prediction.id), "input_type": "url", "status": "completed"},
        )

        assert data["input_data"] == "https://example.com/specific-image.jpg"

    @pytest.mark.asyncio
    async def test_get_prediction_not_found(self, authorized_client: AsyncClient):
        """Test getting prediction that doesn't exist."""
        fake_prediction_id = uuid4()

        response = await authorized_client.get(
            f"/api/v1/predictions/{fake_prediction_id}"
        )

        assert_not_found_error(response)

    @pytest.mark.asyncio
    async def test_get_other_user_prediction(
        self,
        authorized_client: AsyncClient,
        db_session: AsyncSession,
        prediction_factory,
        create_user_factory,
    ):
        """Test that users cannot access other users' predictions."""
        # Create another user and their prediction
        other_user = await create_user_factory(
            email="otheruser@company.com", name="Other User"
        )

        other_prediction = await prediction_factory.create_async(
            db_session,
            user_id=other_user.id,
            input_type="url",
            input_data="https://example.com/other-image.jpg",
        )

        # Try to access the other user's prediction
        response = await authorized_client.get(
            f"/api/v1/predictions/{other_prediction.id}"
        )

        # Should return not found (for security)
        assert_not_found_error(response)


class TestPredictionValidation:
    """Test prediction input validation and error scenarios."""

    @pytest.mark.asyncio
    async def test_create_prediction_invalid_input_type(
        self, authorized_client: AsyncClient
    ):
        """Test creating prediction with invalid input type."""
        invalid_data = {"input_type": "invalid_type", "input_data": "some_data"}

        response = await authorized_client.post(
            "/api/v1/predictions", json=invalid_data
        )

        # Should return validation error
        assert_validation_error(response)

    @pytest.mark.asyncio
    async def test_create_prediction_missing_input_data(
        self, authorized_client: AsyncClient
    ):
        """Test creating prediction without input data."""
        invalid_data = {
            "input_type": "url"
            # Missing input_data
        }

        response = await authorized_client.post(
            "/api/v1/predictions", json=invalid_data
        )

        # Should return validation error
        assert_validation_error(response)

    @pytest.mark.asyncio
    async def test_create_prediction_invalid_url(self, authorized_client: AsyncClient):
        """Test creating prediction with invalid URL."""
        invalid_data = {"input_type": "url", "input_data": "not_a_valid_url"}

        response = await authorized_client.post(
            "/api/v1/predictions", json=invalid_data
        )

        # Should return validation error
        assert_validation_error(response)

    @pytest.mark.asyncio
    async def test_create_prediction_service_failure(
        self, authorized_client: AsyncClient
    ):
        """Test prediction creation when service fails."""
        prediction_data = {
            "input_type": "url",
            "input_data": "https://example.com/failing-image.jpg",
        }

        # Mock service to raise an exception
        with patch(
            "src.modules.prediction.application.use_cases.PredictionService.predict_from_url"
        ) as mock_predict:
            mock_predict.side_effect = Exception("Service unavailable")

            response = await authorized_client.post(
                "/api/v1/predictions", json=prediction_data
            )

        # Should return service error
        assert_error_response(response, MessageCode.PREDICTION_FAILED, 500)


class TestPredictionFileUpload:
    """Test prediction functionality with file uploads."""

    @pytest.mark.asyncio
    async def test_create_prediction_from_file_upload(
        self, authorized_client: AsyncClient
    ):
        """Test creating prediction from file upload."""
        # Create mock image file
        image_content = b"fake_image_data"
        files = {"file": ("test_image.jpg", image_content, "image/jpeg")}

        with patch(
            "src.modules.prediction.application.use_cases.PredictionService.predict_from_upload"
        ) as mock_predict:
            mock_predict.return_value = {
                "latitude": 48.8566,
                "longitude": 2.3522,
                "confidence": 0.78,
            }

            response = await authorized_client.post(
                "/api/v1/predictions/upload", files=files
            )

        # Should succeed
        data = assert_success_response(response, MessageCode.CREATED, 201)

        assert data["input_type"] == "upload"
        assert "prediction_result" in data

    @pytest.mark.asyncio
    async def test_upload_prediction_invalid_file_type(
        self, authorized_client: AsyncClient
    ):
        """Test uploading invalid file type for prediction."""
        # Create mock text file
        text_content = b"this is not an image"
        files = {"file": ("test.txt", text_content, "text/plain")}

        response = await authorized_client.post(
            "/api/v1/predictions/upload", files=files
        )

        # Should return validation error
        assert_error_response(response, MessageCode.INVALID_FILE_TYPE, 400)

    @pytest.mark.asyncio
    async def test_upload_prediction_file_too_large(
        self, authorized_client: AsyncClient
    ):
        """Test uploading file that's too large."""
        # Create mock large file (simulate)
        large_content = b"x" * (10 * 1024 * 1024)  # 10MB
        files = {"file": ("large_image.jpg", large_content, "image/jpeg")}

        response = await authorized_client.post(
            "/api/v1/predictions/upload", files=files
        )

        # Should return file too large error
        assert_error_response(response, MessageCode.FILE_TOO_LARGE, 413)


class TestPredictionCredits:
    """Test prediction credit consumption functionality."""

    @pytest.mark.asyncio
    async def test_prediction_with_insufficient_credits(
        self, authorized_client: AsyncClient
    ):
        """Test creating prediction when user has insufficient credits."""
        prediction_data = {
            "input_type": "url",
            "input_data": "https://example.com/expensive-image.jpg",
        }

        # Mock credit service to return insufficient credits
        with patch(
            "src.modules.billing.use_cases.CreditService.check_and_consume_credits"
        ) as mock_credits:
            mock_credits.return_value = False  # Insufficient credits

            response = await authorized_client.post(
                "/api/v1/predictions", json=prediction_data
            )

        # Should return insufficient credits error
        assert_error_response(
            response, MessageCode.INSUFFICIENT_CREDITS, 402  # Payment required
        )

    @pytest.mark.asyncio
    async def test_prediction_credit_consumption_tracking(
        self, authorized_client: AsyncClient
    ):
        """Test that prediction credit consumption is properly tracked."""
        prediction_data = {
            "input_type": "url",
            "input_data": "https://example.com/tracked-image.jpg",
        }

        # Mock services
        with (
            patch(
                "src.modules.billing.use_cases.CreditService.check_and_consume_credits"
            ) as mock_credits,
            patch(
                "src.modules.prediction.application.use_cases.PredictionService.predict_from_url"
            ) as mock_predict,
        ):

            mock_credits.return_value = True  # Credits available
            mock_predict.return_value = {
                "latitude": 35.6762,
                "longitude": 139.6503,
                "confidence": 0.88,
            }

            response = await authorized_client.post(
                "/api/v1/predictions", json=prediction_data
            )

        # Should succeed
        assert_success_response(response, MessageCode.CREATED, 201)

        # Verify credit service was called
        mock_credits.assert_called_once()


class TestPredictionWorkflows:
    """Test complete prediction workflows end-to-end."""

    @pytest.mark.asyncio
    async def test_complete_prediction_workflow(
        self, authorized_client: AsyncClient, test_user: User
    ):
        """Test complete prediction workflow: create -> check status -> get result."""
        # Step 1: Create prediction
        prediction_data = {
            "input_type": "url",
            "input_data": "https://example.com/workflow-image.jpg",
        }

        with patch(
            "src.modules.prediction.application.use_cases.PredictionService.predict_from_url"
        ) as mock_predict:
            mock_predict.return_value = {
                "latitude": 59.3293,
                "longitude": 18.0686,
                "confidence": 0.91,
                "processing_time_ms": 2100,
            }

            create_response = await authorized_client.post(
                "/api/v1/predictions", json=prediction_data
            )

        created_prediction = assert_success_response(
            create_response, MessageCode.CREATED, 201
        )

        prediction_id = created_prediction["id"]

        # Step 2: Get prediction details
        get_response = await authorized_client.get(
            f"/api/v1/predictions/{prediction_id}"
        )

        _ = assert_success_response(
            get_response,
            MessageCode.SUCCESS,
            200,
            {"id": prediction_id, "status": "completed"},
        )

        # Step 3: Verify prediction appears in user's list
        list_response = await authorized_client.get("/api/v1/predictions")
        predictions_list = assert_success_response(
            list_response, MessageCode.SUCCESS, 200
        )

        # Find our prediction in the list
        found_prediction = next(
            (pred for pred in predictions_list if pred["id"] == prediction_id), None
        )
        assert found_prediction is not None
        assert (
            found_prediction["input_data"] == "https://example.com/workflow-image.jpg"
        )

    @pytest.mark.asyncio
    async def test_batch_predictions_workflow(self, authorized_client: AsyncClient):
        """Test creating multiple predictions in sequence."""
        image_urls = [
            "https://example.com/batch1.jpg",
            "https://example.com/batch2.jpg",
            "https://example.com/batch3.jpg",
        ]

        prediction_ids = []

        # Create multiple predictions
        for url in image_urls:
            prediction_data = {"input_type": "url", "input_data": url}

            with patch(
                "src.modules.prediction.application.use_cases.PredictionService.predict_from_url"
            ) as mock_predict:
                mock_predict.return_value = {
                    "latitude": 37.7749 + len(prediction_ids),  # Vary results
                    "longitude": -122.4194,
                    "confidence": 0.8,
                }

                response = await authorized_client.post(
                    "/api/v1/predictions", json=prediction_data
                )

            data = assert_success_response(response, MessageCode.CREATED, 201)
            prediction_ids.append(data["id"])

        # Verify all predictions are in the user's list
        list_response = await authorized_client.get("/api/v1/predictions")
        predictions_list = assert_success_response(
            list_response, MessageCode.SUCCESS, 200
        )

        found_ids = [pred["id"] for pred in predictions_list]
        for prediction_id in prediction_ids:
            assert prediction_id in found_ids
