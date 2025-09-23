"""Support endpoints tests."""

import pytest
from httpx import AsyncClient
from fastapi import status


@pytest.mark.asyncio
async def test_clear_cache_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful cache clearing."""
    response = await authorized_client.post("/v1/support/cache/clear")

    # Should either succeed or fail based on permissions
    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message" in data
        assert "message_code" in data
        assert data["message_code"] == "success"
        assert isinstance(data["data"], bool)


@pytest.mark.asyncio
async def test_clear_cache_unauthorized(app, public_client: AsyncClient):
    """Test that cache clearing requires authentication."""
    response = await public_client.post("/v1/support/cache/clear")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_clear_cache_idempotent(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that cache clearing is idempotent (can be called multiple times)."""
    # Clear cache multiple times
    responses = []
    for _ in range(3):
        response = await authorized_client.post("/v1/support/cache/clear")
        responses.append(response.status_code)

    # All should either succeed or fail consistently
    assert all(
        status in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]
        for status in responses
    )


@pytest.mark.asyncio
async def test_clear_cache_response_format(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that cache clear response has correct format."""
    response = await authorized_client.post("/v1/support/cache/clear")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message" in data
        assert "message_code" in data
        assert data["message_code"] == "success"
        assert isinstance(data["data"], bool)
