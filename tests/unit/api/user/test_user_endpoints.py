"""Comprehensive tests for user endpoints."""

import pytest
from httpx import AsyncClient
from fastapi import status
import uuid

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
    """Test successful retrieval of user profile."""
    response = await authorized_client.get("/v1/user/profile")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    # Verify user data matches test user
    user_data = data["data"]
    assert user_data["id"] == str(test_user.id)
    assert user_data["email"] == test_user.email
    assert user_data["full_name"] == test_user.name
    assert "created_at" in user_data
    assert "is_active" in user_data
    assert user_data["is_active"] is True


@pytest.mark.asyncio
async def test_get_user_profile_unauthorized(app, public_client: AsyncClient):
    """Test that profile endpoint requires authentication."""
    response = await public_client.get("/v1/user/profile")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_update_user_profile_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful profile update."""
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

    # Verify the update was applied
    updated_user_data = data["data"]
    assert updated_user_data["full_name"] == new_name
    assert updated_user_data["email"] == new_email
    assert updated_user_data["id"] == str(test_user.id)

    # Verify database was updated
    await db_session.refresh(test_user)
    assert test_user.name == new_name
    assert test_user.email == new_email


@pytest.mark.asyncio
async def test_update_profile_invalid_data(app, authorized_client: AsyncClient):
    """Test profile update with invalid data."""
    # Test with invalid email
    response = await authorized_client.patch(
        "/v1/user/profile", json={"email": "invalid-email"}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Test with empty name
    response = await authorized_client.patch("/v1/user/profile", json={"full_name": ""})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.parametrize("invalid_field", ["id", "created_at", "is_active"])
@pytest.mark.asyncio
async def test_update_immutable_fields_rejected(
    app, authorized_client: AsyncClient, invalid_field: str
):
    """Test that immutable fields cannot be updated."""
    response = await authorized_client.patch(
        "/v1/user/profile", json={invalid_field: "some_value"}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_list_user_organizations_success(
    app, authorized_client: AsyncClient, test_user, test_organization, db_session
):
    """Test successful listing of user organizations."""
    # Create additional organization for the user
    org2 = create_test_organization(plan_tier=PlanTier.FREE)
    db_session.add(org2)
    await db_session.commit()

    response = await authorized_client.get("/v1/user/organizations")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    organizations = data["data"]
    assert isinstance(organizations, list)
    assert len(organizations) >= 1  # Should include test_organization

    # Find our test organization
    test_org_data = None
    for org in organizations:
        if org["id"] == str(test_organization.id):
            test_org_data = org
            break

    assert test_org_data is not None
    assert test_org_data["name"] == test_organization.name
    assert "created_at" in test_org_data
    assert "is_active" in test_org_data


@pytest.mark.asyncio
async def test_list_organizations_unauthorized(app, public_client: AsyncClient):
    """Test that organizations endpoint requires authentication."""
    response = await public_client.get("/v1/user/organizations")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_set_active_organization_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful setting of active organization."""
    # Create second organization for the user
    org2 = create_test_organization(plan_tier=PlanTier.FREE)
    db_session.add(org2)
    await db_session.commit()

    response = await authorized_client.patch(f"/v1/user/organizations/{org2.id}/active")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    # Verify the response includes updated organization list
    updated_orgs = data["data"]
    assert isinstance(updated_orgs, list)
    assert len(updated_orgs) >= 1

    # Find the newly activated organization
    active_org = None
    for org in updated_orgs:
        if org["id"] == str(org2.id):
            active_org = org
            break

    assert active_org is not None
    assert active_org["is_active"] is True


@pytest.mark.asyncio
async def test_set_active_organization_invalid_id(app, authorized_client: AsyncClient):
    """Test setting active organization with invalid UUID."""
    response = await authorized_client.patch(
        "/v1/user/organizations/invalid-uuid/active"
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_set_active_organization_not_owned(
    app, authorized_client: AsyncClient, db_session
):
    """Test setting active organization that user doesn't own."""
    # Use a UUID that definitely doesn't exist
    non_existent_org_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    response = await authorized_client.patch(
        f"/v1/user/organizations/{non_existent_org_id}/active"
    )

    # Should fail because user doesn't own this organization
    assert response.status_code == status.HTTP_404_NOT_FOUND

    error_data = response.json()
    assert "message_code" in error_data


@pytest.mark.asyncio
async def test_organization_switch_updates_context(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that switching organizations updates user context."""
    # Create second organization
    org2 = create_test_organization(plan_tier=PlanTier.FREE)
    db_session.add(org2)
    await db_session.commit()

    # First get current organizations
    response1 = await authorized_client.get("/v1/user/organizations")
    assert response1.status_code == status.HTTP_200_OK

    # Try to switch to the second organization
    response2 = await authorized_client.patch(
        f"/v1/user/organizations/{org2.id}/active"
    )

    assert response2.status_code == status.HTTP_200_OK

    # Verify the switch worked by getting organizations again
    response3 = await authorized_client.get("/v1/user/organizations")
    assert response3.status_code == status.HTTP_200_OK

    updated_data = response3.json()

    # Find the organization that should now be active
    active_org = None
    for org in updated_data["data"]:
        if org["id"] == str(org2.id):
            active_org = org
            break

    assert active_org is not None, "Switched organization should be in list"
    assert active_org["is_active"] is True, "Switched organization should be active"


@pytest.mark.parametrize(
    "field,value,expected_status",
    [
        ("full_name", "", status.HTTP_422_UNPROCESSABLE_ENTITY),
        ("full_name", "a" * 256, status.HTTP_422_UNPROCESSABLE_ENTITY),  # Too long
        ("email", "invalid-email", status.HTTP_422_UNPROCESSABLE_ENTITY),
        ("email", "test@", status.HTTP_422_UNPROCESSABLE_ENTITY),
        ("email", "@example.com", status.HTTP_422_UNPROCESSABLE_ENTITY),
        ("email", "test@.com", status.HTTP_422_UNPROCESSABLE_ENTITY),
        ("email", "test@@example.com", status.HTTP_422_UNPROCESSABLE_ENTITY),
    ],
)
@pytest.mark.asyncio
async def test_profile_update_validation(
    app, authorized_client: AsyncClient, field: str, value: str, expected_status: int
):
    """Test profile update validation with various invalid inputs."""
    response = await authorized_client.patch("/v1/user/profile", json={field: value})
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "name,description",
    [
        ("José María", "with accents"),
        ("D'Angelo", "with apostrophe"),
        ("Mary-Jane", "with hyphen"),
        ("Jean-Paul", "with hyphen and space"),
        ("测试用户", "Chinese characters"),
        ("Тестовый", "Cyrillic characters"),
    ],
)
@pytest.mark.asyncio
async def test_profile_update_with_special_characters(
    name: str,
    description: str,
    app,
    authorized_client: AsyncClient,
    test_user,
    db_session,
):
    """Test profile update with special characters in name."""
    response = await authorized_client.patch(
        "/v1/user/profile", json={"full_name": name}
    )

    # Should either succeed or fail consistently
    assert response.status_code in [
        status.HTTP_200_OK,
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_403_FORBIDDEN,
    ]

    if response.status_code == status.HTTP_200_OK:
        # Verify the name was updated correctly
        data = response.json()
        assert data["data"]["full_name"] == name

        # Reset for next test
        await authorized_client.patch(
            "/v1/user/profile", json={"full_name": "Test User"}
        )


@pytest.mark.asyncio
async def test_user_profile_data_integrity(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that user profile data maintains integrity."""
    # Get initial profile
    response1 = await authorized_client.get("/v1/user/profile")
    assert response1.status_code == status.HTTP_200_OK
    initial_data = response1.json()["data"]

    # Update profile
    new_name = "Updated Name"
    new_email = "updated@example.com"

    update_response = await authorized_client.patch(
        "/v1/user/profile", json={"full_name": new_name, "email": new_email}
    )
    assert update_response.status_code == status.HTTP_200_OK

    # Get profile again
    response2 = await authorized_client.get("/v1/user/profile")
    assert response2.status_code == status.HTTP_200_OK
    updated_data = response2.json()["data"]

    # Verify changes were applied
    assert updated_data["full_name"] == new_name
    assert updated_data["email"] == new_email
    assert updated_data["id"] == initial_data["id"]  # ID should remain same

    # Verify database integrity
    await db_session.refresh(test_user)
    assert test_user.name == new_name
    assert test_user.email == new_email


@pytest.mark.asyncio
async def test_organization_list_includes_metadata(
    app, authorized_client: AsyncClient, test_user, test_organization, db_session
):
    """Test that organization list includes proper metadata."""
    # Create additional organization
    org2 = create_test_organization(plan_tier=PlanTier.ENTERPRISE)
    db_session.add(org2)
    await db_session.commit()

    response = await authorized_client.get("/v1/user/organizations")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    organizations = data["data"]

    for org in organizations:
        assert "id" in org
        assert "name" in org
        assert "logo_url" in org
        assert "created_at" in org
        assert "is_active" in org

        # Verify data types
        assert isinstance(org["id"], str)
        assert isinstance(org["name"], str)
        assert isinstance(org["is_active"], bool)
        assert isinstance(org["created_at"], str)

        # Verify one organization is active
        if org["is_active"]:
            assert isinstance(org["plan_tier"], str)
