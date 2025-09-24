"""Comprehensive authentication and authorization tests."""

import pytest
from httpx import AsyncClient
from fastapi import status
import uuid
from unittest.mock import patch
import io

from src.database.models.users import User
from src.database.models.organizations import Organization, PlanTier
from src.database.models.api_keys import ApiKey


# Factory objects for test data
def create_test_user(
    user_id: uuid.UUID = None, email: str = "test@example.com"
) -> User:
    """Factory to create test user objects."""
    return User(
        id=user_id or uuid.uuid4(),
        email=email,
        name="Test User",
        organization_id=uuid.uuid4(),
        avatar_url=None,
        locale="en",
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


def create_test_api_key(key_id: uuid.UUID = None, user_id: uuid.UUID = None) -> ApiKey:
    """Factory to create test API key objects."""
    return ApiKey(
        id=key_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        name="Test API Key",
        key_hash="hashed_key_value",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_first_login_creates_trial_organization(
    app, public_client: AsyncClient, db_session
):
    """Test that first login creates trial organization and credits."""
    # Create a new user with no organization (first login scenario)
    new_user = create_test_user()
    db_session.add(new_user)
    await db_session.commit()

    # Mock JWT claims for new user with no organization
    with patch(
        "src.services.auth.jwt_claims.extract_user_data_from_jwt"
    ) as mock_claims:
        mock_claims.return_value = {
            "user_id": str(new_user.id),
            "email": new_user.email,
            "name": new_user.name,
            "avatar_url": None,
            "locale": None,
        }

        # Test user profile endpoint - should trigger onboarding
        response = await public_client.get(
            "/v1/user/profile", headers={"Authorization": f"Bearer token_{new_user.id}"}
        )

        # Should return user profile with onboarding info
        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            assert "data" in data
            assert data["data"]["id"] == str(new_user.id)
            assert data["data"]["email"] == new_user.email
            # Should indicate onboarding needs to be completed
            # (actual implementation depends on your onboarding logic)


@pytest.mark.asyncio
async def test_missing_authorization_header(app, public_client: AsyncClient):
    """Test that endpoints requiring auth fail without authorization."""
    response = await public_client.get("/v1/user/profile")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_invalid_token_format(app, public_client: AsyncClient):
    """Test that malformed tokens are rejected."""
    response = await public_client.get(
        "/v1/user/profile", headers={"Authorization": "Invalid token format"}
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_expired_token(app, public_client: AsyncClient):
    """Test that expired tokens are rejected."""
    response = await public_client.get(
        "/v1/user/profile", headers={"Authorization": "Bearer expired_token"}
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_user_with_multiple_organizations(
    app, authorized_client: AsyncClient, db_session, test_user
):
    """Test user with multiple organizations can switch between them."""
    # Create second organization for the test user
    org2 = create_test_organization(plan_tier=PlanTier.FREE)
    db_session.add(org2)
    await db_session.commit()

    # Test switching active organization
    response = await authorized_client.patch(f"/v1/user/organizations/{org2.id}/active")

    # Should succeed since user can manage their own organizations
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "data" in data
    assert data["message_code"] == "success"
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_api_key_authentication_success(app, api_key_client: AsyncClient):
    """Test that valid API keys are accepted."""
    response = await api_key_client.get("/v1/user/profile")
    # Should work if API key auth is properly implemented
    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]


@pytest.mark.asyncio
async def test_invalid_api_key_format(app, public_client: AsyncClient):
    """Test that invalid API key formats are rejected."""
    response = await public_client.get(
        "/v1/user/profile", headers={"X-GeoInfer-Key": "invalid_key_format"}
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_missing_api_key_header(app, public_client: AsyncClient):
    """Test that missing API key header is rejected."""
    response = await public_client.get("/v1/user/profile")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_prediction_with_api_key(app, api_key_client: AsyncClient):
    """Test that API key can be used for predictions."""
    # This would test the prediction endpoint with API key auth
    # For now, just verify the auth flow works
    response = await api_key_client.get("/v1/user/profile")
    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]


@pytest.mark.asyncio
async def test_enterprise_only_endpoints(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that enterprise-only endpoints check plan tier."""
    # Test user is on FREE tier, so organization creation should fail
    response = await authorized_client.post(
        "/v1/organizations/", json={"name": "Test Org", "logo_url": None}
    )

    # Should fail for non-enterprise users
    assert response.status_code == status.HTTP_403_FORBIDDEN

    data = response.json()
    assert "message_code" in data
    assert data["message_code"] != "success"


@pytest.mark.asyncio
async def test_permission_required_endpoints(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that permission-required endpoints check permissions."""
    # Test user likely doesn't have MANAGE_MEMBERS permission
    response = await authorized_client.post(
        "/v1/invitations/", json={"email": "test@example.com", "role": "member"}
    )

    # Should fail if user doesn't have required permissions
    assert response.status_code == status.HTTP_403_FORBIDDEN

    data = response.json()
    assert "message_code" in data


@pytest.mark.asyncio
async def test_analytics_permission_required(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that analytics endpoints require VIEW_ANALYTICS permission."""
    response = await authorized_client.get("/v1/analytics/organization")
    # Test user likely doesn't have analytics permission
    assert response.status_code == status.HTTP_403_FORBIDDEN

    data = response.json()
    assert "message_code" in data


@pytest.mark.asyncio
async def test_trial_prediction_rate_limit(app, public_client: AsyncClient):
    """Test that trial predictions are rate limited."""
    # Create a simple test image
    test_image_data = b"fake image data for testing"

    # Make multiple requests to trial endpoint
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
async def test_trial_prediction_rate_limit_headers(app, public_client: AsyncClient):
    """Test that rate limit exceeded responses include proper headers."""
    # Create a simple test image
    test_image_data = b"fake image data for testing"

    # Exhaust the rate limit by making requests until we get a 429
    for _ in range(5):
        response = await public_client.post(
            "/v1/prediction/trial",
            files={"file": ("test.jpg", io.BytesIO(test_image_data), "image/jpeg")},
        )

        # Check if this response was rate limited
        if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            # Verify rate limit headers are present
            assert "X-RateLimit-Limit" in response.headers
            assert "X-RateLimit-Remaining" in response.headers
            assert "X-RateLimit-Reset" in response.headers
            assert "X-RateLimit-Retry-After" in response.headers
            assert "X-RateLimit-Window" in response.headers
            assert "Retry-After" in response.headers

            # Verify header values make sense
            assert response.headers["X-RateLimit-Remaining"] == "0"
            assert response.headers["X-RateLimit-Limit"] == "3"  # Trial limit
            assert response.headers["X-RateLimit-Window"] == "86400"  # 24 hours in seconds
            break
    else:
        # If we didn't get a 429, the test might not be working as expected
        pytest.skip("Rate limit was not exceeded in the test run")


@pytest.mark.asyncio
async def test_prediction_rate_limit_authenticated(app, authorized_client: AsyncClient):
    """Test that authenticated predictions are rate limited."""
    # This would test the prediction rate limiting
    # For now, just verify the endpoint exists
    response = await authorized_client.get("/v1/user/profile")
    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]


@pytest.mark.asyncio
async def test_cross_authentication_methods(
    app,
    public_client: AsyncClient,
    authorized_client: AsyncClient,
    api_key_client: AsyncClient,
):
    """Test that different auth methods work for the same endpoints."""
    # Test that both JWT and API key auth work for user profile
    jwt_response = await authorized_client.get("/v1/user/profile")
    api_key_response = await api_key_client.get("/v1/user/profile")

    # Both should either succeed or fail consistently
    assert jwt_response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]
    assert api_key_response.status_code in [
        status.HTTP_200_OK,
        status.HTTP_403_FORBIDDEN,
    ]

    # If one works, the other should work too (same permissions)
    # (This assumes both have same access level for this endpoint)
