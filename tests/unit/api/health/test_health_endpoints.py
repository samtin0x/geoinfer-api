"""Health check endpoints tests."""

import pytest
from httpx import AsyncClient
from fastapi import status
from unittest.mock import patch


@pytest.mark.asyncio
async def test_root_endpoint_returns_html(app, public_client: AsyncClient):
    """Test that root endpoint returns proper HTML landing page."""
    response = await public_client.get("/")

    assert response.status_code == status.HTTP_200_OK
    assert "text/html" in response.headers.get("content-type", "")

    # Check for expected HTML content
    html_content = response.text
    assert "GeoInfer API" in html_content
    assert "Launch App" in html_content
    assert "Visit Landing Page" in html_content


@pytest.mark.asyncio
async def test_health_check_comprehensive(app, public_client: AsyncClient):
    """Test comprehensive health check endpoint."""
    response = await public_client.get("/health/")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "status" in data
    assert "database" in data
    assert "redis" in data
    assert "overall" in data

    # Overall status should be healthy if all components are healthy
    assert data["overall"] in ["healthy", "degraded", "unhealthy"]

    # Individual components should have status
    assert data["database"] in ["healthy", "unhealthy"]
    assert data["redis"] in ["healthy", "unhealthy"]


@pytest.mark.asyncio
async def test_health_check_database_unhealthy(app, public_client: AsyncClient):
    """Test health check when database is unhealthy."""
    # Mock database to be unhealthy
    with patch(
        "src.services.health.service.HealthService._check_database",
        return_value="unhealthy",
    ):
        response = await public_client.get("/health/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["database"] == "unhealthy"


@pytest.mark.asyncio
async def test_health_check_redis_unhealthy(app, public_client: AsyncClient):
    """Test health check when Redis is unhealthy."""
    # Mock Redis to be unhealthy
    with patch(
        "src.services.health.service.HealthService._check_redis",
        return_value="unhealthy",
    ):
        response = await public_client.get("/health/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["redis"] == "unhealthy"


@pytest.mark.asyncio
async def test_liveness_check(app, public_client: AsyncClient):
    """Test simple liveness check endpoint."""
    response = await public_client.get("/health/liveness")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["status"] == "alive"
    assert data["service"] == "geoinfer-api"


@pytest.mark.asyncio
async def test_health_check_with_service_details(app, public_client: AsyncClient):
    """Test that health check includes service details."""
    response = await public_client.get("/health/")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()

        # Should include timing information
        assert "timestamp" in data
        assert "response_time_ms" in data

        # Response time should be reasonable
        assert data["response_time_ms"] >= 0
        assert data["response_time_ms"] < 10000  # Less than 10 seconds


@pytest.mark.asyncio
async def test_health_check_response_format(app, public_client: AsyncClient):
    """Test that health check response has correct format."""
    response = await public_client.get("/health/")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()

    # Check required fields
    required_fields = [
        "status",
        "database",
        "redis",
        "overall",
        "timestamp",
        "response_time_ms",
    ]

    for field in required_fields:
        assert field in data

    # Check data types
    assert isinstance(data["status"], str)
    assert isinstance(data["database"], str)
    assert isinstance(data["redis"], str)
    assert isinstance(data["overall"], str)
    assert isinstance(data["response_time_ms"], (int, float))

    # Status should be a valid status
    assert data["status"] in ["healthy", "degraded", "unhealthy"]


@pytest.mark.asyncio
async def test_health_check_detailed_error_info(app, public_client: AsyncClient):
    """Test that health check includes detailed error information when unhealthy."""
    # Mock both database and Redis to be unhealthy
    with (
        patch(
            "src.services.health.service.HealthService._check_database",
            return_value="unhealthy",
        ),
        patch(
            "src.services.health.service.HealthService._check_redis",
            return_value="unhealthy",
        ),
    ):

        response = await public_client.get("/health/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data["database"] == "unhealthy"
        assert data["redis"] == "unhealthy"
        assert data["overall"] == "unhealthy"

        # Should include error details
        if "database_error" in data:
            assert data["database_error"] is not None
        if "redis_error" in data:
            assert data["redis_error"] is not None


@pytest.mark.asyncio
async def test_root_endpoint_html_structure(app, public_client: AsyncClient):
    """Test that root endpoint HTML has proper structure."""
    response = await public_client.get("/")

    assert response.status_code == status.HTTP_200_OK

    html_content = response.text

    # Check for essential HTML elements
    assert "<!DOCTYPE html>" in html_content
    assert "<html" in html_content
    assert "<head>" in html_content
    assert "<body>" in html_content
    assert "</html>" in html_content

    # Check for dynamic content
    assert "©" in html_content  # Copyright symbol
    assert "GeoInfer" in html_content

    # Check that year is current or reasonable
    import re

    year_match = re.search(r"© (\d{4})", html_content)
    if year_match:
        year = int(year_match.group(1))
        current_year = 2024  # Update this as needed
        assert current_year - 1 <= year <= current_year + 1


@pytest.mark.asyncio
async def test_root_endpoint_links_are_present(app, public_client: AsyncClient):
    """Test that root endpoint includes required links."""
    response = await public_client.get("/")

    assert response.status_code == status.HTTP_200_OK

    html_content = response.text

    # Should include app and landing page links
    assert "app.geoinfer.com" in html_content
    assert "geoinfer.com" in html_content

    # Should have proper link structure
    assert "href=" in html_content


@pytest.mark.asyncio
async def test_health_check_performance(app, public_client: AsyncClient):
    """Test that health check completes quickly."""
    import time

    start_time = time.time()
    response = await public_client.get("/health/")
    end_time = time.time()

    # Should complete in reasonable time
    assert (end_time - start_time) < 5  # Less than 5 seconds

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        # Response time should be reasonable
        assert data["response_time_ms"] < 5000  # Less than 5 seconds


@pytest.mark.asyncio
async def test_liveness_check_minimum_data(app, public_client: AsyncClient):
    """Test that liveness check returns minimum required data."""
    response = await public_client.get("/health/liveness")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "status" in data
    assert "service" in data
    assert data["status"] == "alive"
    assert data["service"] == "geoinfer-api"

    # Should not include unnecessary fields
    assert "database" not in data
    assert "redis" not in data
    assert "overall" not in data
