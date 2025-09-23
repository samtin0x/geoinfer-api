"""User profile management tests."""

import pytest
from httpx import AsyncClient
from fastapi import status
import uuid
from datetime import datetime, timezone

from src.database.models.users import User
from src.database.models.organizations import Organization, PlanTier
from src.api.user.requests import UserProfileUpdateRequest


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


@pytest.mark.asyncio
async def test_get_user_profile_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful retrieval of user profile with proper assertions."""
    response = await authorized_client.get("/v1/user/profile")

    # Should always succeed for authenticated users
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    # Verify user data matches test user exactly
    user_data = data["data"]
    assert user_data["id"] == str(test_user.id)
    assert user_data["email"] == test_user.email
    assert user_data["full_name"] == test_user.name
    assert user_data["is_active"] is True
    assert "created_at" in user_data
    assert "onboarding_completed" in user_data


@pytest.mark.asyncio
async def test_get_user_profile_unauthorized(app, public_client: AsyncClient):
    """Test that profile endpoint requires authentication."""
    response = await public_client.get("/v1/user/profile")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_update_user_profile_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful profile update with database verification."""
    new_name = "Updated Test User"
    new_email = "updated@example.com"

    update_data = UserProfileUpdateRequest(full_name=new_name, email=new_email)

    response = await authorized_client.patch(
        "/v1/user/profile", json=update_data.model_dump()
    )

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    # Verify the update was applied in response
    updated_user_data = data["data"]
    assert updated_user_data["full_name"] == new_name
    assert updated_user_data["email"] == new_email
    assert updated_user_data["id"] == str(test_user.id)

    # Verify database was updated correctly
    await db_session.refresh(test_user)
    assert test_user.name == new_name
    assert test_user.email == new_email


@pytest.mark.asyncio
async def test_update_user_profile_email_change_validation(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that email changes are properly validated and updated."""

    # Test valid email update
    new_email = "newemail@example.com"
    update_data = UserProfileUpdateRequest(email=new_email)

    response = await authorized_client.patch(
        "/v1/user/profile", json=update_data.model_dump()
    )

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["data"]["email"] == new_email

    # Verify database update
    await db_session.refresh(test_user)
    assert test_user.email == new_email

    # Test invalid email formats should be rejected
    invalid_emails = ["invalid-email", "test@", "@example.com", "test@.com"]

    for invalid_email in invalid_emails:
        response = await authorized_client.patch(
            "/v1/user/profile", json={"email": invalid_email}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_update_user_profile_name_validation(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that name changes are properly validated."""
    # Test valid name updates
    valid_names = [
        "John Doe",
        "José María",
        "D'Angelo",
        "Mary-Jane",
        "Jean-Paul",
        "测试用户",
        "Тестовый",
    ]

    for valid_name in valid_names:
        response = await authorized_client.patch(
            "/v1/user/profile", json={"full_name": valid_name}
        )

        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["data"]["full_name"] == valid_name

        # Verify database update
        await db_session.refresh(test_user)
        assert test_user.name == valid_name

    # Test invalid name cases
    invalid_names = ["", "a" * 256]  # Empty and too long

    for invalid_name in invalid_names:
        response = await authorized_client.patch(
            "/v1/user/profile", json={"full_name": invalid_name}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_update_immutable_fields_rejected(
    app, authorized_client: AsyncClient, test_user
):
    """Test that immutable fields cannot be updated."""
    immutable_fields = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_active": False,
    }

    for field, value in immutable_fields.items():
        response = await authorized_client.patch(
            "/v1/user/profile", json={field: value}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_user_profile_data_integrity(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that user profile data maintains integrity across operations."""
    # Get initial profile
    response1 = await authorized_client.get("/v1/user/profile")
    assert response1.status_code == status.HTTP_200_OK
    initial_data = response1.json()["data"]

    # Update profile multiple times
    updates = [
        {"full_name": "First Update", "email": "first@example.com"},
        {"full_name": "Second Update", "email": "second@example.com"},
        {"full_name": "Third Update", "email": "third@example.com"},
    ]

    for update in updates:
        response = await authorized_client.patch("/v1/user/profile", json=update)
        assert response.status_code == status.HTTP_200_OK

        data = response.json()["data"]
        assert data["full_name"] == update["full_name"]
        assert data["email"] == update["email"]

    # Verify final state in database
    await db_session.refresh(test_user)
    assert test_user.name == "Third Update"
    assert test_user.email == "third@example.com"

    # Verify ID remained consistent
    final_response = await authorized_client.get("/v1/user/profile")
    final_data = final_response.json()["data"]
    assert final_data["id"] == initial_data["id"]
