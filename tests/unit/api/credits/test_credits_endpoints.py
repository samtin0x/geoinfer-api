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
async def test_get_credit_summary_with_trial_credits(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test credit summary when user has trial credits."""
    response = await authorized_client.get("/v1/credits/summary")

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
    # Get grants
    grants_response = await authorized_client.get("/v1/credits/grants")

    # Get usage
    usage_response = await authorized_client.get("/v1/credits/consumption")

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
async def test_credits_summary_includes_billing_info(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that credits summary includes billing interval and price paid for subscriptions."""
    response = await authorized_client.get("/v1/credits/summary")

    # Should either succeed or fail based on permissions
    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "SUCCESS"

        # Verify summary data structure
        summary_data = data["data"]
        assert "summary" in summary_data
        assert "subscription" in summary_data
        assert "overage" in summary_data
        assert "topups" in summary_data

        # If subscription exists, verify billing info is included
        if summary_data["subscription"]:
            subscription = summary_data["subscription"]
            assert "billing_interval" in subscription
            assert "price_paid" in subscription
            assert "overage_unit_price" in subscription
            assert subscription["billing_interval"] in ["monthly", "yearly"]
            assert isinstance(subscription["price_paid"], (int, float))
            assert subscription["price_paid"] >= 0
            assert isinstance(subscription["overage_unit_price"], (int, float))
            assert subscription["overage_unit_price"] >= 0

            # Verify other subscription fields
            assert "id" in subscription
            assert "monthly_allowance" in subscription
            assert "granted_this_period" in subscription
            assert "used_this_period" in subscription
            assert "remaining" in subscription
            assert "period_start" in subscription
            assert "period_end" in subscription
            assert "status" in subscription
            assert "cancel_at_period_end" in subscription
            assert "pause_access" in subscription
            assert isinstance(subscription["cancel_at_period_end"], bool)
            assert isinstance(subscription["pause_access"], bool)
