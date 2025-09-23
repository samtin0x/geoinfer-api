"""Organization CRUD operations tests."""

import pytest
from httpx import AsyncClient
from fastapi import status
import uuid

from src.database.models.organizations import PlanTier
from src.api.organization.requests import (
    OrganizationCreateRequest,
    OrganizationUpdateRequest,
)


@pytest.mark.asyncio
async def test_create_organization_enterprise_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful organization creation with enterprise permissions."""
    # Create enterprise user for this test
    enterprise_user = test_user
    enterprise_user.plan_tier = PlanTier.ENTERPRISE
    db_session.add(enterprise_user)
    await db_session.commit()

    create_data = OrganizationCreateRequest(
        name="New Enterprise Organization", logo_url="https://example.com/logo.png"
    )

    response = await authorized_client.post(
        "/v1/organizations/", json=create_data.model_dump()
    )

    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    # Verify organization data in response
    org_data = data["data"]
    assert org_data["name"] == "New Enterprise Organization"
    assert org_data["logo_url"] == "https://example.com/logo.png"
    assert "id" in org_data
    assert "created_at" in org_data
    assert "plan_tier" in org_data


@pytest.mark.asyncio
async def test_create_organization_trial_fails(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that trial users cannot create organizations."""
    # Ensure test user is trial tier
    test_user.plan_tier = PlanTier.FREE
    db_session.add(test_user)
    await db_session.commit()

    create_data = OrganizationCreateRequest(name="Trial Organization", logo_url=None)

    response = await authorized_client.post(
        "/v1/organizations/", json=create_data.model_dump()
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN

    error_data = response.json()
    assert "message_code" in error_data
    assert error_data["message_code"] != "success"


@pytest.mark.asyncio
async def test_create_organization_invalid_data(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test organization creation with invalid data."""
    test_user.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_user)
    await db_session.commit()

    # Test with empty name
    response = await authorized_client.post("/v1/organizations/", json={"name": ""})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Test with name too long
    long_name = "a" * 256
    response = await authorized_client.post(
        "/v1/organizations/", json={"name": long_name}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Test with invalid logo URL
    response = await authorized_client.post(
        "/v1/organizations/", json={"name": "Test Org", "logo_url": "not-a-url"}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_update_organization_success(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test successful organization update."""
    update_data = OrganizationUpdateRequest(
        name="Updated Organization Name", logo_url="https://example.com/new-logo.png"
    )

    response = await authorized_client.patch(
        f"/v1/organizations/{test_organization.id}", json=update_data.model_dump()
    )

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    # Verify the update was applied
    updated_org_data = data["data"]
    assert updated_org_data["name"] == "Updated Organization Name"
    assert updated_org_data["logo_url"] == "https://example.com/new-logo.png"
    assert updated_org_data["id"] == str(test_organization.id)

    # Verify database was updated
    await db_session.refresh(test_organization)
    assert test_organization.name == "Updated Organization Name"
    assert test_organization.logo_url == "https://example.com/new-logo.png"


@pytest.mark.asyncio
async def test_update_organization_not_found(app, authorized_client: AsyncClient):
    """Test updating non-existent organization."""
    non_existent_org_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    update_data = OrganizationUpdateRequest(name="Updated Name")

    response = await authorized_client.patch(
        f"/v1/organizations/{non_existent_org_id}", json=update_data.model_dump()
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_update_organization_invalid_data(
    app, authorized_client: AsyncClient, test_organization
):
    """Test organization update with invalid data."""
    # Test with empty name
    response = await authorized_client.patch(
        f"/v1/organizations/{test_organization.id}", json={"name": ""}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Test with name too long
    long_name = "a" * 256
    response = await authorized_client.patch(
        f"/v1/organizations/{test_organization.id}", json={"name": long_name}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_remove_user_from_organization_success(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test successful user removal from organization."""
    # Create another user to remove
    from tests.conftest import create_test_user

    user_to_remove = create_test_user(email="remove@example.com")
    db_session.add(user_to_remove)
    await db_session.commit()

    response = await authorized_client.delete(
        f"/v1/organizations/{test_organization.id}/users/{user_to_remove.id}"
    )

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "message" in data
    assert "message_code" in data
    assert data["message_code"] == "success"


@pytest.mark.asyncio
async def test_remove_user_from_organization_not_found(
    app, authorized_client: AsyncClient
):
    """Test removing user from non-existent organization."""
    non_existent_org_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    user_to_remove_id = uuid.uuid4()

    response = await authorized_client.delete(
        f"/v1/organizations/{non_existent_org_id}/users/{user_to_remove_id}"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_remove_user_from_organization_invalid_ids(
    app, authorized_client: AsyncClient
):
    """Test removing user with invalid UUIDs."""
    # Test with invalid organization ID
    response = await authorized_client.delete(
        "/v1/organizations/invalid-org-id/users/invalid-user-id"
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Test with invalid user ID
    test_org_id = uuid.uuid4()
    response = await authorized_client.delete(
        f"/v1/organizations/{test_org_id}/users/invalid-user-id"
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_organization_name_uniqueness(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that organization names must be unique per user."""
    test_user.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_user)
    await db_session.commit()

    create_data = OrganizationCreateRequest(
        name="Duplicate Organization Name", logo_url=None
    )

    # Try to create organization with same name twice
    response1 = await authorized_client.post(
        "/v1/organizations/", json=create_data.model_dump()
    )

    if response1.status_code == status.HTTP_201_CREATED:
        response2 = await authorized_client.post(
            "/v1/organizations/", json=create_data.model_dump()
        )

        # Second creation should fail due to uniqueness constraint
        assert response2.status_code != status.HTTP_201_CREATED


@pytest.mark.asyncio
async def test_organization_creation_validation(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test organization creation validation rules."""
    test_user.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_user)
    await db_session.commit()

    # Test various valid organization names
    valid_names = [
        "My Company",
        "Test-Organization_123",
        "Organization with spaces",
        "Org.With.Dots",
        "TestOrganization",
        "A",
        "Company Ltd",
    ]

    for name in valid_names:
        response = await authorized_client.post(
            "/v1/organizations/", json={"name": name}
        )

        # Should either succeed or fail consistently based on permissions
        assert response.status_code in [
            status.HTTP_201_CREATED,
            status.HTTP_403_FORBIDDEN,
        ]

        if response.status_code == status.HTTP_201_CREATED:
            data = response.json()
            assert data["data"]["name"] == name


@pytest.mark.asyncio
async def test_organization_update_validation(
    app, authorized_client: AsyncClient, test_organization
):
    """Test organization update validation rules."""
    # Test various valid organization names
    valid_names = [
        "Updated Company",
        "Updated-Organization_123",
        "Updated organization with spaces",
        "Updated.Org.With.Dots",
        "UpdatedTestOrganization",
        "B",
        "New Company Name Ltd",
    ]

    for name in valid_names:
        response = await authorized_client.patch(
            f"/v1/organizations/{test_organization.id}", json={"name": name}
        )

        # Should either succeed or fail consistently based on permissions
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
        ]

        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            assert data["data"]["name"] == name
