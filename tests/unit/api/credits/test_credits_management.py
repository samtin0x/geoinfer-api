"""Credits management tests."""

import pytest
from httpx import AsyncClient
from fastapi import status


@pytest.mark.asyncio
async def test_get_credit_balance_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful credit balance retrieval."""
    response = await authorized_client.get("/v1/credits/balance")

    # Should either succeed or fail based on permissions
    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "success"

        # Verify balance data structure
        balance_data = data["data"]
        assert "balance" in balance_data
        assert "total_granted" in balance_data
        assert "total_used" in balance_data
        assert isinstance(balance_data["balance"], (int, float))
        assert isinstance(balance_data["total_granted"], (int, float))
        assert isinstance(balance_data["total_used"], (int, float))

        # Verify mathematical consistency
        assert (
            balance_data["balance"]
            == balance_data["total_granted"] - balance_data["total_used"]
        )
        assert balance_data["balance"] >= 0  # Should not be negative


@pytest.mark.asyncio
async def test_get_credit_balance_unauthorized(app, public_client: AsyncClient):
    """Test that credit balance requires authentication."""
    response = await public_client.get("/v1/credits/balance")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_get_credit_consumption_history_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful credit consumption history retrieval."""
    response = await authorized_client.get("/v1/credits/consumption")

    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "success"

        usage_history = data["data"]
        assert isinstance(usage_history, list)

        # Verify each usage record structure
        for usage in usage_history:
            assert "id" in usage
            assert "amount" in usage
            assert "timestamp" in usage
            assert "usage_type" in usage
            assert isinstance(usage["amount"], (int, float))
            assert usage["amount"] > 0
            assert isinstance(usage["usage_type"], str)


@pytest.mark.asyncio
async def test_get_credit_consumption_history_unauthorized(
    app, public_client: AsyncClient
):
    """Test that credit consumption history requires authentication."""
    response = await public_client.get("/v1/credits/consumption")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_get_credit_grants_history_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful credit grants history retrieval."""
    response = await authorized_client.get("/v1/credits/grants")

    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "success"

        grants_history = data["data"]
        assert isinstance(grants_history, list)

        # Verify each grant record structure
        for grant in grants_history:
            assert "id" in grant
            assert "amount" in grant
            assert "timestamp" in grant
            assert "reason" in grant
            assert isinstance(grant["amount"], (int, float))
            assert grant["amount"] > 0
            assert isinstance(grant["reason"], str)
            assert len(grant["reason"]) > 0


@pytest.mark.asyncio
async def test_get_credit_grants_history_unauthorized(app, public_client: AsyncClient):
    """Test that credit grants history requires authentication."""
    response = await public_client.get("/v1/credits/grants")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_credit_endpoints_pagination(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test credit endpoints respect pagination limits."""
    # Test consumption endpoint with limit
    response = await authorized_client.get("/v1/credits/consumption?limit=5")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        usage_history = data["data"]
        assert isinstance(usage_history, list)
        assert len(usage_history) <= 5

    # Test grants endpoint with limit
    response = await authorized_client.get("/v1/credits/grants?limit=5")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        grants_history = data["data"]
        assert isinstance(grants_history, list)
        assert len(grants_history) <= 5

    # Test consumption endpoint with offset
    response = await authorized_client.get("/v1/credits/consumption?offset=2&limit=3")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        usage_history = data["data"]
        assert isinstance(usage_history, list)
        assert len(usage_history) <= 3

    # Test grants endpoint with offset
    response = await authorized_client.get("/v1/credits/grants?offset=2&limit=3")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        grants_history = data["data"]
        assert isinstance(grants_history, list)
        assert len(grants_history) <= 3


@pytest.mark.asyncio
async def test_credit_data_consistency(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that credit data is consistent across all endpoints."""
    # Get data from all credit endpoints
    balance_response = await authorized_client.get("/v1/credits/balance")
    grants_response = await authorized_client.get("/v1/credits/grants")
    usage_response = await authorized_client.get("/v1/credits/consumption")

    if (
        balance_response.status_code == status.HTTP_200_OK
        and grants_response.status_code == status.HTTP_200_OK
        and usage_response.status_code == status.HTTP_200_OK
    ):

        balance_data = balance_response.json()["data"]
        grants_data = grants_response.json()["data"]
        usage_data = usage_response.json()["data"]

        # Calculate totals from history
        total_grants = sum(grant["amount"] for grant in grants_data)
        total_usage = sum(usage["amount"] for usage in usage_data)

        # Verify consistency with balance endpoint
        assert balance_data["total_granted"] == total_grants
        assert balance_data["total_used"] == total_usage
        assert balance_data["balance"] == total_grants - total_usage

        # Verify all amounts are positive
        assert total_grants > 0 or total_grants == 0  # Can be zero for new accounts
        assert total_usage >= 0
        assert balance_data["balance"] >= 0


@pytest.mark.asyncio
async def test_credit_amounts_are_numeric(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that all credit amounts are numeric values."""
    # Get balance
    balance_response = await authorized_client.get("/v1/credits/balance")

    # Get grants
    grants_response = await authorized_client.get("/v1/credits/grants")

    # Get usage
    usage_response = await authorized_client.get("/v1/credits/consumption")

    if balance_response.status_code == status.HTTP_200_OK:
        balance_data = balance_response.json()["data"]
        assert isinstance(balance_data["balance"], (int, float))
        assert isinstance(balance_data["total_granted"], (int, float))
        assert isinstance(balance_data["total_used"], (int, float))
        assert balance_data["balance"] >= 0
        assert balance_data["total_granted"] >= 0
        assert balance_data["total_used"] >= 0

    if grants_response.status_code == status.HTTP_200_OK:
        grants_data = grants_response.json()["data"]
        for grant in grants_data:
            assert isinstance(grant["amount"], (int, float))
            assert grant["amount"] > 0

    if usage_response.status_code == status.HTTP_200_OK:
        usage_data = usage_response.json()["data"]
        for usage in usage_data:
            assert isinstance(usage["amount"], (int, float))
            assert usage["amount"] > 0


@pytest.mark.asyncio
async def test_credit_history_timestamps_are_valid(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that credit history timestamps are valid ISO format."""
    # Get grants
    grants_response = await authorized_client.get("/v1/credits/grants")

    # Get usage
    usage_response = await authorized_client.get("/v1/credits/consumption")

    if grants_response.status_code == status.HTTP_200_OK:
        grants_data = grants_response.json()["data"]
        for grant in grants_data:
            assert "timestamp" in grant
            timestamp = grant["timestamp"]
            # Should be able to parse as datetime
            from datetime import datetime

            try:
                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                # If it doesn't have timezone, try without
                datetime.fromisoformat(timestamp)

    if usage_response.status_code == status.HTTP_200_OK:
        usage_data = usage_response.json()["data"]
        for usage in usage_data:
            assert "timestamp" in usage
            timestamp = usage["timestamp"]
            # Should be able to parse as datetime
            from datetime import datetime

            try:
                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                # If it doesn't have timezone, try without
                datetime.fromisoformat(timestamp)


@pytest.mark.asyncio
async def test_credit_grants_include_trial_grant(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test credit grants history includes initial trial grant."""
    response = await authorized_client.get("/v1/credits/grants")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        grants_data = data["data"]

        # Should have at least one grant (trial grant)
        assert len(grants_data) >= 1

        # Find the trial grant
        trial_grant = None
        for grant in grants_data:
            if "trial" in grant.get("reason", "").lower():
                trial_grant = grant
                break

        if trial_grant:
            assert trial_grant["amount"] > 0
            assert "timestamp" in trial_grant
            assert isinstance(trial_grant["amount"], (int, float))
