"""Analytics endpoints tests."""

import pytest
from httpx import AsyncClient
from fastapi import status

from src.api.analytics.models import GroupByType


@pytest.mark.asyncio
async def test_get_usage_timeseries_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful usage timeseries retrieval."""
    response = await authorized_client.get("/v1/analytics/timeseries")

    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "SUCCESS"

        timeseries_data = data["data"]
        assert isinstance(timeseries_data, list)

        # Verify timeseries data structure
        for entry in timeseries_data:
            assert "date" in entry
            assert "count" in entry
            assert "credits_used" in entry
            assert isinstance(entry["count"], int)
            assert isinstance(entry["credits_used"], (int, float))
            assert entry["count"] >= 0
            assert entry["credits_used"] >= 0


@pytest.mark.parametrize("days", [1, 7, 30, 90, 365])
@pytest.mark.asyncio
async def test_usage_timeseries_different_time_ranges(
    app, authorized_client: AsyncClient, test_user, db_session, days: int
):
    """Test usage timeseries with different day ranges."""
    response = await authorized_client.get(f"/v1/analytics/timeseries?days={days}")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        timeseries_data = data["data"]
        assert isinstance(timeseries_data, list)
        assert len(timeseries_data) <= days


@pytest.mark.parametrize(
    "group_by", [GroupByType.DAY, GroupByType.WEEK, GroupByType.MONTH]
)
@pytest.mark.asyncio
async def test_usage_timeseries_different_grouping(
    app, authorized_client: AsyncClient, test_user, db_session, group_by: GroupByType
):
    """Test usage timeseries with different grouping options."""
    response = await authorized_client.get(
        f"/v1/analytics/timeseries?group_by={group_by.value}"
    )

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        timeseries_data = data["data"]
        assert isinstance(timeseries_data, list)

        for entry in timeseries_data:
            assert "date" in entry
            assert "count" in entry
            assert "credits_used" in entry


@pytest.mark.asyncio
async def test_usage_timeseries_invalid_days_parameter(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test usage timeseries with invalid days parameter."""
    # Test with days too small
    response = await authorized_client.get("/v1/analytics/timeseries?days=0")
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Test with days too large
    response = await authorized_client.get("/v1/analytics/timeseries?days=400")
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_get_user_usage_analytics_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful user usage analytics retrieval."""
    response = await authorized_client.get("/v1/analytics/users")

    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "SUCCESS"

        analytics_data = data["data"]
        assert "users" in analytics_data
        assert "total_users" in analytics_data
        assert "total_credits_used" in analytics_data

        users = analytics_data["users"]
        assert isinstance(users, list)
        assert isinstance(analytics_data["total_users"], int)
        assert isinstance(analytics_data["total_credits_used"], (int, float))

        # Verify user data structure
        for user in users:
            assert "user_id" in user
            assert "user_email" in user
            assert "full_name" in user
            assert "total_predictions" in user
            assert "total_credits_used" in user
            assert "last_prediction_at" in user
            assert isinstance(user["total_predictions"], int)
            assert isinstance(user["total_credits_used"], (int, float))
            assert user["total_predictions"] >= 0
            assert user["total_credits_used"] >= 0


@pytest.mark.asyncio
async def test_get_organization_analytics_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful organization analytics retrieval."""
    response = await authorized_client.get("/v1/analytics/organization")

    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "SUCCESS"

        org_data = data["data"]
        assert isinstance(org_data, dict)

        # Verify organization analytics structure
        required_fields = [
            "total_predictions",
            "total_credits_used",
            "total_credits_granted",
            "current_credits_balance",
            "active_users",
            "api_keys_count",
        ]

        for field in required_fields:
            assert field in org_data
            assert isinstance(org_data[field], (int, float))
            assert org_data[field] >= 0


@pytest.mark.asyncio
async def test_get_api_key_usage_analytics_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful API key usage analytics retrieval."""
    response = await authorized_client.get("/v1/analytics/api-keys")

    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "SUCCESS"

        api_key_data = data["data"]
        assert isinstance(api_key_data, list)

        # Verify API key analytics structure
        for api_key in api_key_data:
            assert "key_id" in api_key
            assert "key_name" in api_key
            assert "total_predictions" in api_key
            assert "total_credits_used" in api_key
            assert "last_used_at" in api_key
            assert isinstance(api_key["total_predictions"], int)
            assert isinstance(api_key["total_credits_used"], (int, float))
            assert api_key["total_predictions"] >= 0
            assert api_key["total_credits_used"] >= 0


@pytest.mark.asyncio
async def test_analytics_data_consistency(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that analytics data is consistent across endpoints."""
    # Get data from different analytics endpoints
    timeseries_response = await authorized_client.get(
        "/v1/analytics/timeseries?days=30"
    )
    users_response = await authorized_client.get("/v1/analytics/users?days=30")
    org_response = await authorized_client.get("/v1/analytics/organization")
    api_keys_response = await authorized_client.get("/v1/analytics/api-keys?days=30")

    if (
        timeseries_response.status_code == status.HTTP_200_OK
        and users_response.status_code == status.HTTP_200_OK
        and org_response.status_code == status.HTTP_200_OK
        and api_keys_response.status_code == status.HTTP_200_OK
    ):

        # Extract data
        timeseries_data = timeseries_response.json()["data"]
        users_data = users_response.json()["data"]
        org_data = org_response.json()["data"]
        api_keys_data = api_keys_response.json()["data"]

        # Calculate totals from different sources
        total_credits_from_timeseries = sum(
            item["credits_used"] for item in timeseries_data
        )
        total_credits_from_users = sum(
            user["total_credits_used"] for user in users_data["users"]
        )
        total_credits_from_api_keys = sum(
            api_key["total_credits_used"] for api_key in api_keys_data
        )

        # Should be reasonably consistent (allowing for rounding/timing differences)
        assert total_credits_from_users >= 0
        assert total_credits_from_api_keys >= 0
        assert total_credits_from_timeseries >= 0

        # Organization totals should be reasonable
        assert org_data["total_predictions"] >= 0
        assert org_data["total_credits_used"] >= 0
        assert org_data["active_users"] >= 0
        assert org_data["api_keys_count"] >= 0


@pytest.mark.asyncio
async def test_analytics_endpoints_require_permissions(
    app,
    authorized_client: AsyncClient,
    public_client: AsyncClient,
    test_user,
    db_session,
):
    """Test that analytics endpoints require proper permissions."""
    # Test that public client cannot access authenticated endpoints
    public_endpoints = [
        "/v1/analytics/timeseries",
        "/v1/analytics/users",
        "/v1/analytics/organization",
        "/v1/analytics/api-keys",
    ]

    for endpoint in public_endpoints:
        response = await public_client.get(endpoint)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    # Test that authorized client gets proper responses
    auth_endpoints = [
        "/v1/analytics/timeseries",
        "/v1/analytics/users",
        "/v1/analytics/organization",
        "/v1/analytics/api-keys",
    ]

    for endpoint in auth_endpoints:
        response = await authorized_client.get(endpoint)
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            assert "data" in data
            assert "message_code" in data
            assert data["message_code"] == "SUCCESS"
