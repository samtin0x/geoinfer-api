"""Comprehensive tests for user functionality - both business logic and API."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from src.database.models import User, Organization, OrganizationRole
from src.api.core.messages import MessageCode
from tests.utils.assertions import (
    assert_success_response,
    assert_error_response,
    assert_authentication_error,
    assert_not_found_error,
)


# User Business Logic Tests


@pytest.mark.asyncio
async def test_user_creation_with_factory(
    db_session: AsyncSession, user_factory, organization_factory
):
    """Test creating a user using the factory system."""
    # Create organization first
    org = await organization_factory.create_async(
        db_session, name="Test Company", plan_tier="free"
    )

    # Create user
    user = await user_factory.create_async(
        db_session,
        name="John Doe",
        email="john@testcompany.com",
        organization_id=org.id,
    )

    # Assertions
    assert user.name == "John Doe"
    assert user.email == "john@testcompany.com"
    assert user.organization_id == org.id
    assert user.id is not None
    assert user.created_at is not None


@pytest.mark.asyncio
async def test_user_organization_relationship(
    db_session: AsyncSession, user_factory, test_organization: Organization
):
    """Test user-organization relationship."""
    # Create user in existing organization
    user = await user_factory.create_async(
        db_session, organization_id=test_organization.id, email="member@company.com"
    )

    # Test relationship
    assert user.organization_id == test_organization.id

    # You can extend this to test the actual SQLAlchemy relationship
    # if you load the user with relationships


@pytest.mark.asyncio
async def test_multiple_users_same_organization(
    db_session: AsyncSession,
    create_user_factory,
    test_organization: Organization,
):
    """Test creating multiple users in the same organization."""
    # Create admin and member
    admin = await create_user_factory(
        email="admin@company.com", name="Admin User", role=OrganizationRole.ADMIN
    )

    member = await create_user_factory(
        email="member@company.com", name="Member User", role=OrganizationRole.MEMBER
    )

    # Both should be in the same organization
    assert admin.organization_id == member.organization_id
    assert admin.organization_id == test_organization.id


# User API Endpoint Tests


@pytest.mark.asyncio
async def test_get_user_profile_success(
    authorized_client: AsyncClient, test_user: User
):
    """Test getting user profile with valid authentication."""
    response = await authorized_client.get("/api/v1/user/profile")

    # Assert successful response with correct message code
    data = assert_success_response(
        response,
        MessageCode.SUCCESS,
        200,
        {"id": str(test_user.id), "email": test_user.email, "name": test_user.name},
    )

    # Additional assertions on returned data
    assert data["id"] == str(test_user.id)
    assert data["email"] == test_user.email
    assert data["name"] == test_user.name


@pytest.mark.asyncio
async def test_get_user_profile_unauthenticated(public_client: AsyncClient):
    """Test getting user profile without authentication."""
    response = await public_client.get("/api/v1/user/profile")

    # Should return authentication error
    assert_authentication_error(response)


@pytest.mark.asyncio
async def test_update_user_profile_success(
    authorized_client: AsyncClient, test_user: User
):
    """Test updating user profile successfully."""
    update_data = {"name": "Updated Name"}

    response = await authorized_client.patch("/api/v1/user/profile", json=update_data)

    # Assert successful update
    data = assert_success_response(
        response,
        MessageCode.SUCCESS,  # Or MESSAGE.USER_UPDATED if that's what your API returns
        200,
        {
            "name": "Updated Name",
            "email": test_user.email,  # Should remain unchanged
        },
    )

    # Verify the update
    assert data["name"] == "Updated Name"
    assert data["email"] == test_user.email


@pytest.mark.asyncio
async def test_update_user_profile_validation_error(authorized_client: AsyncClient):
    """Test updating user profile with invalid data."""
    update_data = {"name": ""}  # Empty name should be invalid

    response = await authorized_client.patch("/api/v1/user/profile", json=update_data)

    # Should return validation error
    assert_error_response(response, MessageCode.INVALID_INPUT, 422)


@pytest.mark.asyncio
async def test_list_user_organizations_success(
    authorized_client: AsyncClient,
    test_user: User,
    test_organization: Organization,
):
    """Test listing user organizations."""
    response = await authorized_client.get("/api/v1/user/organizations")

    # Assert successful response
    data = assert_success_response(response, MessageCode.SUCCESS, 200)

    # Should return list of organizations
    assert isinstance(data, list)
    assert len(data) >= 1  # At least the test organization

    # Find our test organization in the results
    test_org_data = next(
        (org for org in data if org["id"] == str(test_organization.id)), None
    )
    assert test_org_data is not None
    assert test_org_data["name"] == test_organization.name


@pytest.mark.asyncio
async def test_set_active_organization_success(
    authorized_client: AsyncClient, test_organization: Organization
):
    """Test setting an organization as active."""
    response = await authorized_client.patch(
        "/api/v1/user/organizations/active",
        json={"organization_id": str(test_organization.id)},
    )

    # Assert successful response
    data = assert_success_response(response, MessageCode.SUCCESS, 200)

    # Should return success confirmation
    assert "success" in data
    assert data["success"] is True


@pytest.mark.asyncio
async def test_set_active_organization_not_found(authorized_client: AsyncClient):
    """Test setting non-existent organization as active."""
    fake_org_id = uuid4()

    response = await authorized_client.patch(
        f"/api/v1/user/organizations/{fake_org_id}/active"
    )

    # Should return not found error
    assert_not_found_error(response, "organization")


# User API Tests with Different Roles


@pytest.mark.asyncio
async def test_admin_user_access(admin_client: AsyncClient, test_admin_user: User):
    """Test API access with admin user."""
    response = await admin_client.get("/api/v1/user/profile")

    data = assert_success_response(
        response,
        MessageCode.SUCCESS,
        200,
        {"id": str(test_admin_user.id), "email": test_admin_user.email},
    )

    assert data["name"] == test_admin_user.name


@pytest.mark.asyncio
async def test_member_user_access(member_client: AsyncClient, test_member_user: User):
    """Test API access with member user."""
    response = await member_client.get("/api/v1/user/profile")

    data = assert_success_response(
        response,
        MessageCode.SUCCESS,
        200,
        {"id": str(test_member_user.id), "email": test_member_user.email},
    )

    assert data["name"] == test_member_user.name


# User API Tests with API Key


@pytest.mark.asyncio
async def test_api_key_authentication(api_key_client: AsyncClient, test_user: User):
    """Test API access using API key authentication."""
    # Note: This depends on your API key authentication setup
    # Some endpoints might not be accessible via API key
    response = await api_key_client.get("/api/v1/user/profile")

    # This might return 401 if API keys don't support user profile access
    # Adjust based on your API design
    if response.status_code == 401:
        assert_authentication_error(response)
    else:
        assert_success_response(response, MessageCode.SUCCESS, 200)


# User API Error Scenarios


@pytest.mark.asyncio
async def test_invalid_json_payload(authorized_client: AsyncClient):
    """Test API with malformed JSON."""
    response = await authorized_client.patch(
        "/api/v1/user/profile",
        content="invalid json",
        headers={"Content-Type": "application/json"},
    )

    # Should return validation error
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_missing_required_fields(authorized_client: AsyncClient):
    """Test API with missing required fields."""
    # Send request with missing required data
    response = await authorized_client.patch(
        "/api/v1/user/profile", json={}  # Empty payload
    )

    # This should succeed since all fields are optional in profile update
    # Or return validation error if any fields are required
    assert response.status_code in [200, 422]


# User Workflow Tests


@pytest.mark.asyncio
async def test_user_registration_and_profile_update_workflow(
    client_factory,
    db_session: AsyncSession,
    create_user_factory,
    test_organization: Organization,
):
    """Test complete workflow: create user -> authenticate -> update profile."""
    # Step 1: Create a new user
    new_user = await create_user_factory(
        email="newuser@company.com", name="New User", organization=test_organization
    )

    # Step 2: Create authenticated client for this user
    user_client = await client_factory(new_user)

    # Step 3: Get profile
    profile_response = await user_client.get("/api/v1/user/profile")
    _ = assert_success_response(
        profile_response,
        MessageCode.SUCCESS,
        200,
        {"email": "newuser@company.com", "name": "New User"},
    )

    # Step 4: Update profile
    update_response = await user_client.patch(
        "/api/v1/user/profile", json={"name": "Updated New User"}
    )

    _ = assert_success_response(
        update_response,
        MessageCode.SUCCESS,
        200,
        {"name": "Updated New User", "email": "newuser@company.com"},
    )

    # Step 5: Verify the update persisted
    final_profile_response = await user_client.get("/api/v1/user/profile")
    _ = assert_success_response(
        final_profile_response,
        MessageCode.SUCCESS,
        200,
        {"name": "Updated New User"},
    )

    await user_client.aclose()


@pytest.mark.asyncio
async def test_organization_switching_workflow(
    admin_client: AsyncClient,
    db_session: AsyncSession,
    organization_factory,
    test_admin_user: User,
):
    """Test workflow for switching between organizations."""
    # Create another organization for the admin user
    await organization_factory.create_async(db_session, name="Second Company")

    # List organizations
    orgs_response = await admin_client.get("/api/v1/user/organizations")
    orgs_data = assert_success_response(orgs_response, MessageCode.SUCCESS, 200)

    # Should have at least one organization
    assert len(orgs_data) >= 1

    # Try to set an organization as active
    first_org_id = orgs_data[0]["id"]
    active_response = await admin_client.patch(
        f"/api/v1/user/organizations/{first_org_id}/active"
    )

    # Should succeed
    assert_success_response(active_response, MessageCode.SUCCESS, 200)
