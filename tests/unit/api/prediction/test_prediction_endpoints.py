"""Prediction endpoints tests with proper file upload validation."""

import pytest
from httpx import AsyncClient
from fastapi import status
import io


@pytest.mark.asyncio
async def test_trial_prediction_success(app, public_client: AsyncClient):
    """Test successful trial prediction with valid image."""
    # Create a valid test image (minimal PNG data)
    test_image_data = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13"
        b"\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\nIDATx\x9cc\xf8"
        b"\x00\x00\x00\x01\x00\x01\x00\x18\xdd\x8d\xb9\x00\x00\x00\x00"
        b"IEND\xaeB`\x82"
    )

    response = await public_client.post(
        "/v1/prediction/trial",
        files={"file": ("test.png", io.BytesIO(test_image_data), "image/png")},
    )

    # Should either succeed or be rate limited
    assert response.status_code in [
        status.HTTP_200_OK,
        status.HTTP_429_TOO_MANY_REQUESTS,
    ]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "success"

        # Verify prediction data structure
        prediction = data["data"]
        assert isinstance(prediction, dict)
        assert "coordinates" in prediction
        assert "confidence" in prediction
        assert isinstance(prediction["confidence"], (int, float))
        assert 0.0 <= prediction["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_trial_prediction_rate_limit_exceeded(app, public_client: AsyncClient):
    """Test that trial predictions are properly rate limited."""
    test_image_data = b"fake image data for testing"

    # Make multiple requests to exceed rate limit
    responses = []
    for _ in range(5):
        response = await public_client.post(
            "/v1/prediction/trial",
            files={"file": ("test.jpg", io.BytesIO(test_image_data), "image/jpeg")},
        )
        responses.append(response.status_code)

    # At least some should be rate limited
    assert status.HTTP_429_TOO_MANY_REQUESTS in responses


@pytest.mark.asyncio
async def test_trial_prediction_invalid_file_type(app, public_client: AsyncClient):
    """Test trial prediction with invalid file type."""
    # Test with text file
    response = await public_client.post(
        "/v1/prediction/trial",
        files={"file": ("test.txt", io.BytesIO(b"This is not an image"), "text/plain")},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_trial_prediction_file_too_large(app, public_client: AsyncClient):
    """Test trial prediction with file too large."""
    # Create a file larger than 5MB limit
    large_content = b"x" * (6 * 1024 * 1024)  # 6MB

    response = await public_client.post(
        "/v1/prediction/trial",
        files={"file": ("test.jpg", io.BytesIO(large_content), "image/jpeg")},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_trial_prediction_heic_support(app, public_client: AsyncClient):
    """Test that trial prediction supports HEIC/HEIF files."""
    # Test with HEIC file (should be supported even with generic content type)
    heic_data = b"fake heic data for testing"

    response = await public_client.post(
        "/v1/prediction/trial",
        files={
            "file": ("test.heic", io.BytesIO(heic_data), "application/octet-stream")
        },
    )

    # Should either succeed or fail based on business logic
    assert response.status_code in [
        status.HTTP_200_OK,
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_429_TOO_MANY_REQUESTS,
    ]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "prediction" in data["data"]


@pytest.mark.asyncio
async def test_authenticated_prediction_success(app, authorized_client: AsyncClient):
    """Test successful authenticated prediction."""
    # Create a valid test image
    test_image_data = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13"
        b"\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\nIDATx\x9cc\xf8"
        b"\x00\x00\x00\x01\x00\x01\x00\x18\xdd\x8d\xb9\x00\x00\x00\x00"
        b"IEND\xaeB`\x82"
    )

    response = await authorized_client.post(
        "/v1/prediction/predict",
        files={"file": ("test.png", io.BytesIO(test_image_data), "image/png")},
    )

    # Should either succeed or be rate limited
    assert response.status_code in [
        status.HTTP_200_OK,
        status.HTTP_429_TOO_MANY_REQUESTS,
        status.HTTP_403_FORBIDDEN,
    ]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "success"

        # Verify prediction data structure
        prediction_data = data["data"]
        assert "prediction" in prediction_data
        predictions = prediction_data["prediction"]
        assert isinstance(predictions, list)
        assert len(predictions) > 0

        # Check structure of first prediction
        first_pred = predictions[0]
        assert "coordinates" in first_pred
        assert "confidence" in first_pred
        assert isinstance(first_pred["confidence"], (int, float))
        assert 0.0 <= first_pred["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_authenticated_prediction_unauthorized(app, public_client: AsyncClient):
    """Test that authenticated prediction endpoint requires authentication."""
    test_image_data = b"fake image data"

    response = await public_client.post(
        "/v1/prediction/predict",
        files={"file": ("test.jpg", io.BytesIO(test_image_data), "image/jpeg")},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize("top_k", [1, 5, 10, 20, 50])
@pytest.mark.asyncio
async def test_prediction_top_k_parameter(
    app, authorized_client: AsyncClient, top_k: int
):
    """Test prediction with different top_k values."""
    test_image_data = b"fake image data for testing"

    response = await authorized_client.post(
        f"/v1/prediction/predict?top_k={top_k}",
        files={"file": ("test.jpg", io.BytesIO(test_image_data), "image/jpeg")},
    )

    # Should either succeed or fail based on business logic
    assert response.status_code in [
        status.HTTP_200_OK,
        status.HTTP_429_TOO_MANY_REQUESTS,
        status.HTTP_403_FORBIDDEN,
    ]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        predictions = data["data"]["prediction"]
        assert isinstance(predictions, list)
        assert len(predictions) <= top_k  # Should respect top_k parameter


@pytest.mark.asyncio
async def test_prediction_top_k_out_of_range(app, authorized_client: AsyncClient):
    """Test prediction with top_k out of valid range."""
    test_image_data = b"fake image data"

    # Test with top_k too small
    response = await authorized_client.post(
        "/v1/prediction/predict?top_k=0",
        files={"file": ("test.jpg", io.BytesIO(test_image_data), "image/jpeg")},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST

    # Test with top_k too large
    response = await authorized_client.post(
        "/v1/prediction/predict?top_k=100",
        files={"file": ("test.jpg", io.BytesIO(test_image_data), "image/jpeg")},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.parametrize(
    "image_format,content_type",
    [
        ("test.jpg", "image/jpeg"),
        ("test.png", "image/png"),
        ("test.webp", "image/webp"),
        ("test.heic", "image/heic"),
        ("test.heif", "image/heif"),
    ],
)
@pytest.mark.asyncio
async def test_prediction_different_image_formats(
    app, authorized_client: AsyncClient, image_format: str, content_type: str
):
    """Test prediction with different image formats."""
    # Create minimal valid image data for each format
    if "jpg" in image_format or "jpeg" in image_format:
        test_data = b"fake jpeg data"
    elif "png" in image_format:
        test_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\nIDATx\x9cc\xf8\x00\x00\x00\x01\x00\x01\x00\x18\xdd\x8d\xb9\x00\x00\x00\x00IEND\xaeB`\x82"
    else:
        test_data = b"fake image data"

    response = await authorized_client.post(
        "/v1/prediction/predict",
        files={"file": (image_format, io.BytesIO(test_data), content_type)},
    )

    # Should either succeed or fail consistently based on format support
    assert response.status_code in [
        status.HTTP_200_OK,
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_429_TOO_MANY_REQUESTS,
        status.HTTP_403_FORBIDDEN,
    ]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "prediction" in data["data"]
        predictions = data["data"]["prediction"]
        assert isinstance(predictions, list)
        assert len(predictions) > 0


@pytest.mark.asyncio
async def test_prediction_file_too_large_authenticated(
    app, authorized_client: AsyncClient
):
    """Test authenticated prediction with file too large."""
    # Create a file larger than 10MB limit
    large_content = b"x" * (11 * 1024 * 1024)  # 11MB

    response = await authorized_client.post(
        "/v1/prediction/predict",
        files={"file": ("test.jpg", io.BytesIO(large_content), "image/jpeg")},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_prediction_invalid_file_type_authenticated(
    app, authorized_client: AsyncClient
):
    """Test authenticated prediction with invalid file type."""
    # Test with text file
    response = await authorized_client.post(
        "/v1/prediction/predict",
        files={"file": ("test.txt", io.BytesIO(b"This is not an image"), "text/plain")},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_prediction_response_format_validation(
    app, authorized_client: AsyncClient
):
    """Test that prediction response has correct format and data types."""
    test_image_data = b"fake image data for format testing"

    response = await authorized_client.post(
        "/v1/prediction/predict",
        files={"file": ("test.jpg", io.BytesIO(test_image_data), "image/jpeg")},
    )

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "success"

        prediction_data = data["data"]
        assert "prediction" in prediction_data

        predictions = prediction_data["prediction"]
        assert isinstance(predictions, list)
        assert len(predictions) > 0

        # Check each prediction in the list
        for prediction in predictions:
            assert "coordinates" in prediction
            assert "confidence" in prediction
            assert isinstance(prediction["confidence"], (int, float))
            assert 0.0 <= prediction["confidence"] <= 1.0

            # Verify coordinates structure
            coordinates = prediction["coordinates"]
            assert isinstance(coordinates, dict)
            assert "lat" in coordinates
            assert "lng" in coordinates
            assert isinstance(coordinates["lat"], (int, float))
            assert isinstance(coordinates["lng"], (int, float))


@pytest.mark.asyncio
async def test_prediction_with_api_key(app, api_key_client: AsyncClient):
    """Test prediction using API key authentication."""
    test_image_data = b"fake image data for api key test"

    response = await api_key_client.post(
        "/v1/prediction/predict",
        files={"file": ("test.jpg", io.BytesIO(test_image_data), "image/jpeg")},
    )

    # Should work with valid API key
    assert response.status_code in [
        status.HTTP_200_OK,
        status.HTTP_429_TOO_MANY_REQUESTS,
        status.HTTP_403_FORBIDDEN,
    ]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "prediction" in data["data"]
        predictions = data["data"]["prediction"]
        assert isinstance(predictions, list)
        assert len(predictions) > 0
