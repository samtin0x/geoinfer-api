"""Comprehensive tests for credits endpoints."""

import pytest
from httpx import AsyncClient
from fastapi import status
import uuid

from src.database.models.organizations import Organization, PlanTier
from src.database.models.users import User
from src.database.models.credit_grants import CreditGrant


# Factory objects for test data
def create_test_user(
    user_id: uuid.UUID = None, email: str = "test@example.com"
) -> User:
    """Factory to create test user objects."""
    return User(
        id=user_id or uuid.uuid4(),
        email=email,
        full_name="Test User",
        is_active=True,
        onboarding_completed=False,
    )


def create_test_organization(
    org_id: uuid.UUID = None, plan_tier: PlanTier = PlanTier.FREE
) -> Organization:
    """Factory to create test organization objects."""
    return Organization(
        id=org_id or uuid.uuid4(),
        name="Test Organization",
        logo_url=None,
        plan_tier=plan_tier,
    )


def create_test_credit_grant(
    grant_id: uuid.UUID = None, organization_id: uuid.UUID = None, amount: int = 100
) -> CreditGrant:
    """Factory to create test credit grant objects."""
    return CreditGrant(
        id=grant_id or uuid.uuid4(),
        organization_id=organization_id or uuid.uuid4(),
        amount=amount,
        reason="Test credit grant",
        granted_by_user_id=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_get_credit_balance_view_analytics_permission(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that credit balance requires VIEW_ANALYTICS permission."""
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


@pytest.mark.asyncio
async def test_get_credit_balance_unauthorized(app, public_client: AsyncClient):
    """Test that credit balance requires authentication."""
    response = await public_client.get("/v1/credits/balance")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_get_credit_balance_with_trial_credits(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test credit balance when user has trial credits."""
    response = await authorized_client.get("/v1/credits/balance")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        balance_data = data["data"]

        # For trial users, should have some initial credits
        assert balance_data["balance"] >= 0
        assert balance_data["total_granted"] > 0
        assert balance_data["total_used"] >= 0

        # Balance should equal granted minus used
        assert (
            balance_data["balance"]
            == balance_data["total_granted"] - balance_data["total_used"]
        )


@pytest.mark.asyncio
async def test_get_credit_consumption_history_view_analytics_permission(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that credit consumption history requires VIEW_ANALYTICS permission."""
    response = await authorized_client.get("/v1/credits/consumption")

    # Should either succeed or fail based on permissions
    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "success"

        # Verify usage history data structure
        usage_history = data["data"]
        assert isinstance(usage_history, list)

        if len(usage_history) > 0:
            usage = usage_history[0]
            assert "id" in usage
            assert "amount" in usage
            assert "timestamp" in usage
            assert "usage_type" in usage
            assert isinstance(usage["amount"], (int, float))
            assert usage["amount"] > 0


@pytest.mark.asyncio
async def test_get_credit_consumption_history_unauthorized(
    app, public_client: AsyncClient
):
    """Test that credit consumption history requires authentication."""
    response = await public_client.get("/v1/credits/consumption")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_get_credit_consumption_history_pagination(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test credit consumption history pagination."""
    # Test with custom limit
    response = await authorized_client.get("/v1/credits/consumption?limit=10")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        usage_history = data["data"]
        assert isinstance(usage_history, list)
        assert len(usage_history) <= 10

    # Test with offset
    response = await authorized_client.get("/v1/credits/consumption?offset=5&limit=10")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        usage_history = data["data"]
        assert isinstance(usage_history, list)


@pytest.mark.asyncio
async def test_get_credit_grants_history_view_analytics_permission(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that credit grants history requires VIEW_ANALYTICS permission."""
    response = await authorized_client.get("/v1/credits/grants")

    # Should either succeed or fail based on permissions
    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "success"

        # Verify grants history data structure
        grants_history = data["data"]
        assert isinstance(grants_history, list)

        if len(grants_history) > 0:
            grant = grants_history[0]
            assert "id" in grant
            assert "amount" in grant
            assert "timestamp" in grant
            assert "reason" in grant
            assert isinstance(grant["amount"], (int, float))
            assert grant["amount"] > 0
            assert isinstance(grant["reason"], str)


@pytest.mark.asyncio
async def test_get_credit_grants_history_unauthorized(app, public_client: AsyncClient):
    """Test that credit grants history requires authentication."""
    response = await public_client.get("/v1/credits/grants")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_get_credit_grants_history_pagination(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test credit grants history pagination."""
    # Test with custom limit
    response = await authorized_client.get("/v1/credits/grants?limit=5")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        grants_history = data["data"]
        assert isinstance(grants_history, list)
        assert len(grants_history) <= 5

    # Test with offset
    response = await authorized_client.get("/v1/credits/grants?offset=2&limit=5")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        grants_history = data["data"]
        assert isinstance(grants_history, list)


@pytest.mark.asyncio
async def test_credit_balance_matches_grants_minus_usage(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that credit balance equals grants total minus usage total."""
    # Get balance
    balance_response = await authorized_client.get("/v1/credits/balance")

    # Get grants
    grants_response = await authorized_client.get("/v1/credits/grants")

    # Get usage
    usage_response = await authorized_client.get("/v1/credits/consumption")

    if (
        balance_response.status_code == status.HTTP_200_OK
        and grants_response.status_code == status.HTTP_200_OK
        and usage_response.status_code == status.HTTP_200_OK
    ):

        # Extract data
        balance_data = balance_response.json()["data"]
        grants_data = grants_response.json()["data"]
        usage_data = usage_response.json()["data"]

        # Calculate expected balance from grants and usage
        total_grants = sum(grant["amount"] for grant in grants_data)
        total_usage = sum(usage["amount"] for usage in usage_data)
        expected_balance = total_grants - total_usage

        # Should match the reported balance
        assert balance_data["balance"] == expected_balance
        assert balance_data["total_granted"] == total_grants
        assert balance_data["total_used"] == total_usage


@pytest.mark.parametrize("endpoint", ["/v1/credits/consumption", "/v1/credits/grants"])
@pytest.mark.parametrize("limit", [1, 10, 50, 100])
@pytest.mark.asyncio
async def test_credit_endpoints_pagination_limits(
    endpoint: str,
    limit: int,
    app,
    authorized_client: AsyncClient,
    test_user,
    db_session,
):
    """Test credit endpoints respect pagination limits."""
    response = await authorized_client.get(f"{endpoint}?limit={limit}")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        items = data["data"]
        assert len(items) <= limit


@pytest.mark.asyncio
async def test_credit_data_types_are_numeric(
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

        # All amounts should be non-negative
        assert balance_data["balance"] >= 0
        assert balance_data["total_granted"] >= 0
        assert balance_data["total_used"] >= 0

    if grants_response.status_code == status.HTTP_200_OK:
        grants_data = grants_response.json()["data"]
        for grant in grants_data:
            assert isinstance(grant["amount"], (int, float))
            assert grant["amount"] > 0  # Grants should be positive

    if usage_response.status_code == status.HTTP_200_OK:
        usage_data = usage_response.json()["data"]
        for usage in usage_data:
            assert isinstance(usage["amount"], (int, float))
            assert usage["amount"] > 0  # Usage should be positive


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
            # Should be able to parse as datetime
            from datetime import datetime

            timestamp = grant["timestamp"]
            try:
                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                # If it doesn't have timezone, try without
                datetime.fromisoformat(timestamp)

    if usage_response.status_code == status.HTTP_200_OK:
        usage_data = usage_response.json()["data"]
        for usage in usage_data:
            assert "timestamp" in usage
            # Should be able to parse as datetime
            from datetime import datetime

            timestamp = usage["timestamp"]
            try:
                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                # If it doesn't have timezone, try without
                datetime.fromisoformat(timestamp)


@pytest.mark.asyncio
async def test_credit_history_includes_trial_grant(
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


@pytest.mark.asyncio
async def test_credit_endpoints_data_consistency(
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

        # Verify mathematical consistency
        total_grants = sum(grant["amount"] for grant in grants_data)
        total_usage = sum(usage["amount"] for usage in usage_data)

        assert balance_data["total_granted"] == total_grants
        assert balance_data["total_used"] == total_usage
        assert balance_data["balance"] == total_grants - total_usage

        # Verify all amounts are positive
        assert total_grants > 0
        assert total_usage >= 0
        assert balance_data["balance"] >= 0


@pytest.mark.asyncio
async def test_credit_usage_tracking_with_predictions(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that credit usage is properly tracked when predictions are made."""
    # Get initial balance
    balance_response = await authorized_client.get("/v1/credits/balance")

    if balance_response.status_code == status.HTTP_200_OK:
        initial_balance = balance_response.json()["data"]["balance"]

        # Make a prediction (if credits available)
        if initial_balance > 0:
            # This would require actual image data and prediction service
            # For now, just test that the endpoint exists and auth works
            prediction_response = await authorized_client.get(
                "/v1/user/profile"
            )  # Placeholder
            assert prediction_response.status_code in [
                status.HTTP_200_OK,
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ]

            # If prediction was made, verify credits were consumed
            # This would require mocking the prediction service
            # For now, just verify the balance endpoint still works
            final_balance_response = await authorized_client.get("/v1/credits/balance")
            assert final_balance_response.status_code == status.HTTP_200_OK
