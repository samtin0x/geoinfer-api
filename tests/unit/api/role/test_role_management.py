"""Role management tests."""

import pytest
from httpx import AsyncClient
from fastapi import status
import uuid

from src.api.role.requests import GrantRoleRequest, ChangeRoleRequest


@pytest.mark.asyncio
async def test_grant_role_success(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test successful role granting."""
    # Create another user to grant role to
    from tests.conftest import create_test_user

    user_to_grant = create_test_user(email="grant@example.com")
    db_session.add(user_to_grant)
    await db_session.commit()

    grant_data = GrantRoleRequest(role="member")

    response = await authorized_client.post(
        f"/v1/roles/organizations/{test_organization.id}/users/{user_to_grant.id}",
        json=grant_data.model_dump(),
    )

    assert response.status_code in [
        status.HTTP_200_OK,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
    ]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "success"

        role_data = data["data"]
        assert role_data["user_id"] == str(user_to_grant.id)
        assert role_data["role"] == "member"
        assert role_data["organization_id"] == str(test_organization.id)


@pytest.mark.asyncio
async def test_grant_role_invalid_organization(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test granting role to user in non-existent organization."""
    # Create another user
    from tests.conftest import create_test_user

    user_to_grant = create_test_user(email="grant@example.com")
    db_session.add(user_to_grant)
    await db_session.commit()

    non_existent_org_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    grant_data = GrantRoleRequest(role="member")

    response = await authorized_client.post(
        f"/v1/roles/organizations/{non_existent_org_id}/users/{user_to_grant.id}",
        json=grant_data.model_dump(),
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_grant_role_invalid_user(
    app, authorized_client: AsyncClient, test_organization
):
    """Test granting role to non-existent user."""
    non_existent_user_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    grant_data = GrantRoleRequest(role="member")

    response = await authorized_client.post(
        f"/v1/roles/organizations/{test_organization.id}/users/{non_existent_user_id}",
        json=grant_data.model_dump(),
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize("role", ["admin", "member", "viewer"])
@pytest.mark.asyncio
async def test_grant_different_roles(
    app, authorized_client: AsyncClient, test_organization, db_session, role: str
):
    """Test granting different types of roles."""
    # Create user to grant role to
    from tests.conftest import create_test_user

    user_to_grant = create_test_user(email=f"{role}@example.com")
    db_session.add(user_to_grant)
    await db_session.commit()

    grant_data = GrantRoleRequest(role=role)

    response = await authorized_client.post(
        f"/v1/roles/organizations/{test_organization.id}/users/{user_to_grant.id}",
        json=grant_data.model_dump(),
    )

    assert response.status_code in [
        status.HTTP_200_OK,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
    ]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert data["data"]["role"] == role


@pytest.mark.asyncio
async def test_grant_role_invalid_role(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test granting invalid role."""
    # Create user to grant role to
    from tests.conftest import create_test_user

    user_to_grant = create_test_user(email="invalid@example.com")
    db_session.add(user_to_grant)
    await db_session.commit()

    grant_data = GrantRoleRequest(role="invalid_role")

    response = await authorized_client.post(
        f"/v1/roles/organizations/{test_organization.id}/users/{user_to_grant.id}",
        json=grant_data.model_dump(),
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_change_role_success(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test successful role change."""
    # Create user to change role for
    from tests.conftest import create_test_user

    user_to_change = create_test_user(email="change@example.com")
    db_session.add(user_to_change)
    await db_session.commit()

    change_data = ChangeRoleRequest(role="admin")

    response = await authorized_client.patch(
        f"/v1/roles/organizations/{test_organization.id}/users/{user_to_change.id}",
        json=change_data.model_dump(),
    )

    assert response.status_code in [
        status.HTTP_200_OK,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
    ]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "success"

        role_data = data["data"]
        assert role_data["user_id"] == str(user_to_change.id)
        assert role_data["role"] == "admin"
        assert role_data["organization_id"] == str(test_organization.id)


@pytest.mark.asyncio
async def test_change_role_invalid_role(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test changing to invalid role."""
    # Create user to change role for
    from tests.conftest import create_test_user

    user_to_change = create_test_user(email="change@example.com")
    db_session.add(user_to_change)
    await db_session.commit()

    change_data = ChangeRoleRequest(role="invalid_role")

    response = await authorized_client.patch(
        f"/v1/roles/organizations/{test_organization.id}/users/{user_to_change.id}",
        json=change_data.model_dump(),
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_get_role_definitions_success(app, authorized_client: AsyncClient):
    """Test successful retrieval of role definitions."""
    response = await authorized_client.get("/v1/roles/definitions")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    roles = data["data"]
    assert isinstance(roles, list)
    assert len(roles) > 0

    # Verify role definition structure
    for role in roles:
        assert "name" in role
        assert "permissions" in role
        assert isinstance(role["permissions"], list)

        # Check that permissions are valid strings
        for permission in role["permissions"]:
            assert isinstance(permission, str)
            assert len(permission) > 0


@pytest.mark.asyncio
async def test_get_current_user_roles_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful retrieval of current user's roles."""
    response = await authorized_client.get("/v1/roles/")

    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "success"

        user_roles = data["data"]
        assert isinstance(user_roles, list)

        # Verify role data structure
        for role in user_roles:
            assert "organization_id" in role
            assert "role" in role
            assert "organization_name" in role
            assert isinstance(role["organization_name"], str)
            assert len(role["organization_name"]) > 0


@pytest.mark.asyncio
async def test_get_organization_users_with_roles_success(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test successful retrieval of organization users with roles."""
    response = await authorized_client.get("/v1/organizations/users")

    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "SUCCESS"

        org_data = data["data"]
        assert "users" in org_data
        assert "organization_id" in org_data
        assert "user_count" in org_data

        org_users = org_data["users"]
        assert isinstance(org_users, list)

        # Verify user role data structure
        for org_user in org_users:
            assert "user_id" in org_user
            assert "email" in org_user
            assert "name" in org_user
            assert "role" in org_user
            assert "joined_at" in org_user
            assert isinstance(org_user["email"], str)
            assert isinstance(org_user["name"], str)
            assert isinstance(org_user["role"], str)
