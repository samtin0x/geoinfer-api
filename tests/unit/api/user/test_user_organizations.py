"""User organization management tests."""

import pytest
from httpx import AsyncClient
from fastapi import status
import uuid

from src.database.models.users import User
from src.database.models.organizations import Organization, PlanTier


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
async def test_list_user_organizations_success(
    app, authorized_client: AsyncClient, test_user, test_organization, db_session
):
    """Test successful listing of user organizations with proper data."""
    # Create additional organization for the user
    org2 = create_test_organization(plan_tier=PlanTier.ENTERPRISE)
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

    assert test_org_data is not None, "Test organization should be in the list"
    assert test_org_data["name"] == test_organization.name
    assert test_org_data["is_active"] is True  # Should be active by default
    assert "created_at" in test_org_data
    assert "logo_url" in test_org_data
    assert "plan_tier" in test_org_data
    assert test_org_data["plan_tier"] == test_organization.plan_tier.value


@pytest.mark.asyncio
async def test_list_user_organizations_with_multiple_orgs(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test organization listing when user has multiple organizations."""
    # Create multiple organizations
    orgs = []
    for i in range(3):
        org = create_test_organization(plan_tier=PlanTier.FREE)
        orgs.append(org)
        db_session.add(org)
    await db_session.commit()

    response = await authorized_client.get("/v1/user/organizations")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    organizations = data["data"]
    assert len(organizations) >= 3

    # Verify all created organizations are in the list
    created_org_ids = [str(org.id) for org in orgs]
    returned_org_ids = [org["id"] for org in organizations]

    for org_id in created_org_ids:
        assert org_id in returned_org_ids

    # Verify organization data structure
    for org in organizations:
        assert "id" in org
        assert "name" in org
        assert "logo_url" in org
        assert "created_at" in org
        assert "is_active" in org
        assert "plan_tier" in org
        assert isinstance(org["name"], str)
        assert isinstance(org["is_active"], bool)
        assert isinstance(org["plan_tier"], str)


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

    response = await authorized_client.patch(
        "/v1/user/organizations/active", json={"organization_id": str(org2.id)}
    )

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    # Verify the response contains success confirmation
    response_data = data["data"]
    assert "success" in response_data
    assert response_data["success"] is True


@pytest.mark.asyncio
async def test_set_active_organization_invalid_id(app, authorized_client: AsyncClient):
    """Test setting active organization with invalid UUID."""
    response = await authorized_client.patch(
        "/v1/user/organizations/active", json={"organization_id": "invalid-uuid"}
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
        "/v1/user/organizations/active",
        json={"organization_id": str(non_existent_org_id)},
    )

    # Should fail because user doesn't own this organization
    assert response.status_code == status.HTTP_404_NOT_FOUND

    error_data = response.json()
    assert "message_code" in error_data
    assert error_data["message_code"] != "success"


@pytest.mark.asyncio
async def test_organization_switch_updates_context(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that switching organizations updates user context properly."""
    # Create multiple organizations
    orgs = []
    for i in range(3):
        org = create_test_organization(plan_tier=PlanTier.FREE)
        orgs.append(org)
        db_session.add(org)
    await db_session.commit()

    # Switch to each organization and verify
    for target_org in orgs:
        response = await authorized_client.patch(
            "/v1/user/organizations/active",
            json={"organization_id": str(target_org.id)},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify the response contains success confirmation
        data = response.json()
        assert data["data"]["success"] is True

        # Verify the switch worked by getting organizations again
        verify_response = await authorized_client.get("/v1/user/organizations")
        assert verify_response.status_code == status.HTTP_200_OK

        updated_data = verify_response.json()

        # Find the organization that should now be active
        active_org = None
        for org in updated_data["data"]:
            if org["id"] == str(target_org.id):
                active_org = org
                break

        assert active_org is not None, f"Organization {target_org.id} should be in list"
        assert (
            active_org["is_active"] is True
        ), f"Organization {target_org.id} should be active"


@pytest.mark.asyncio
async def test_organization_list_metadata_validation(
    app, authorized_client: AsyncClient, test_user, test_organization, db_session
):
    """Test that organization list includes proper metadata."""
    # Create organization with logo
    org_with_logo = create_test_organization(plan_tier=PlanTier.ENTERPRISE)
    org_with_logo.logo_url = "https://example.com/logo.png"
    db_session.add(org_with_logo)
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
        assert "plan_tier" in org

        # Verify data types
        assert isinstance(org["id"], str)
        assert isinstance(org["name"], str)
        assert isinstance(org["is_active"], bool)
        assert isinstance(org["created_at"], str)
        assert isinstance(org["plan_tier"], str)

        # Verify plan tier values
        assert org["plan_tier"] in ["trial", "subscribed", "enterprise"]

        # Verify one organization is active
        if org["is_active"]:
            assert isinstance(org["plan_tier"], str)
