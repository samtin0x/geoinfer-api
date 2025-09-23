"""Invitation management tests with proper business logic."""

import pytest
from httpx import AsyncClient
from fastapi import status
import uuid
from datetime import datetime, timezone

from src.database.models.users import User
from src.database.models.organizations import Organization, PlanTier
from src.database.models.invitations import Invitation
from src.api.invitation.requests import (
    InvitationCreateRequest,
)


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
    org_id: uuid.UUID = None, plan_tier: PlanTier = PlanTier.ENTERPRISE
) -> Organization:
    """Factory to create test organization objects."""
    return Organization(
        id=org_id or uuid.uuid4(),
        name="Test Organization",
        logo_url=None,
        plan_tier=plan_tier,
    )


def create_test_invitation(
    invitation_id: uuid.UUID = None,
    organization_id: uuid.UUID = None,
    email: str = "invited@example.com",
) -> Invitation:
    """Factory to create test invitation objects."""
    return Invitation(
        id=invitation_id or uuid.uuid4(),
        organization_id=organization_id or uuid.uuid4(),
        email=email,
        role="member",
        token=str(uuid.uuid4()),
        status="pending",
        expires_at=datetime.now(timezone.utc).replace(
            hour=23, minute=59, second=59, microsecond=0
        ),
    )


@pytest.mark.asyncio
async def test_create_invitation_enterprise_organization(
    app, authorized_client: AsyncClient, test_user, test_organization, db_session
):
    """Test creating invitation with enterprise organization."""
    # Ensure test organization is enterprise tier
    test_organization.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_organization)
    await db_session.commit()

    # Create an invitation
    create_data = InvitationCreateRequest(email="invited@example.com", role="member")

    response = await authorized_client.post(
        "/v1/invitations/", json=create_data.model_dump()
    )

    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    # Verify invitation data in response
    invitation_data = data["data"]
    assert invitation_data["email"] == "invited@example.com"
    assert invitation_data["status"] == "pending"
    assert "organization_id" in invitation_data
    assert "id" in invitation_data
    assert "invited_by_id" in invitation_data
    assert "expires_at" in invitation_data
    assert "created_at" in invitation_data
    # Token should not be exposed in API responses for security reasons
    assert "token" not in invitation_data


@pytest.mark.asyncio
async def test_create_invitation_trial_organization_fails(
    app, authorized_client: AsyncClient, test_user, test_organization, db_session
):
    """Test that invitation creation fails for trial organizations."""
    # Ensure test organization is trial tier
    test_organization.plan_tier = PlanTier.FREE
    db_session.add(test_organization)
    await db_session.commit()

    create_data = InvitationCreateRequest(email="invited@example.com", role="member")

    response = await authorized_client.post(
        "/v1/invitations/", json=create_data.model_dump()
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_create_invitation_invalid_email(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test invitation creation with invalid email formats."""
    test_organization.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_organization)
    await db_session.commit()

    invalid_emails = [
        "invalid-email",
        "test@",
        "@example.com",
        "test@.com",
        "",
        "a" * 256 + "@example.com",
    ]

    for email in invalid_emails:
        create_data = InvitationCreateRequest(email=email, role="member")

        response = await authorized_client.post(
            "/v1/invitations/", json=create_data.model_dump()
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_create_invitation_invalid_role(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test invitation creation with invalid roles."""
    test_organization.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_organization)
    await db_session.commit()

    invalid_roles = ["", "invalid_role", "super_admin"]

    for role in invalid_roles:
        create_data = InvitationCreateRequest(email="test@example.com", role=role)

        response = await authorized_client.post(
            "/v1/invitations/", json=create_data.model_dump()
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_list_organization_invitations_enterprise(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test listing invitations for enterprise organization."""
    test_organization.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_organization)
    await db_session.commit()

    # Create multiple invitations
    invitations = []
    for i in range(3):
        invitation = create_test_invitation(
            organization_id=test_organization.id, email=f"user{i}@example.com"
        )
        invitations.append(invitation)
        db_session.add(invitation)
    await db_session.commit()

    response = await authorized_client.get("/v1/invitations/list")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    invitations_list = data["data"]
    assert len(invitations_list) >= 3

    # Verify all created invitations are in the list
    created_emails = [inv.email for inv in invitations]
    returned_emails = [inv["email"] for inv in invitations_list]

    for email in created_emails:
        assert email in returned_emails


@pytest.mark.asyncio
async def test_list_organization_invitations_trial_fails(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test that listing invitations fails for trial organizations."""
    test_organization.plan_tier = PlanTier.FREE
    db_session.add(test_organization)
    await db_session.commit()

    response = await authorized_client.get("/v1/invitations/list")

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_cancel_invitation_management(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test invitation cancellation by organization managers."""
    test_organization.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_organization)
    await db_session.commit()

    # Create an invitation
    invitation = create_test_invitation(
        organization_id=test_organization.id, email="cancel@example.com"
    )
    db_session.add(invitation)
    await db_session.commit()

    # Cancel the invitation
    response = await authorized_client.delete(f"/v1/invitations/{invitation.id}")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "message" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    # Verify the invitation status was updated
    await db_session.refresh(invitation)
    assert invitation.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_nonexistent_invitation(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test cancelling non-existent invitation."""
    test_organization.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_organization)
    await db_session.commit()

    non_existent_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    response = await authorized_client.delete(f"/v1/invitations/{non_existent_id}")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_invitation_data_validation(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test that invitation data is properly validated."""
    test_organization.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_organization)
    await db_session.commit()

    # Test with valid data
    valid_data = InvitationCreateRequest(email="valid@example.com", role="member")

    response = await authorized_client.post(
        "/v1/invitations/", json=valid_data.model_dump()
    )

    assert response.status_code == status.HTTP_201_CREATED

    invitation_data = response.json()["data"]
    assert invitation_data["email"] == "valid@example.com"
    assert invitation_data["role"] == "member"
    assert invitation_data["status"] == "pending"

    # Test with different roles
    roles = ["admin", "member", "viewer"]
    for role in roles:
        role_data = InvitationCreateRequest(email=f"{role}@example.com", role=role)

        response = await authorized_client.post(
            "/v1/invitations/", json=role_data.model_dump()
        )

        assert response.status_code == status.HTTP_201_CREATED

        role_invitation_data = response.json()["data"]
        assert role_invitation_data["role"] == role
