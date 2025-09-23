"""Invitation acceptance and decline tests."""

import pytest
from httpx import AsyncClient
from fastapi import status
import uuid
from datetime import datetime, timezone

from src.database.models.users import User
from src.database.models.organizations import Organization, PlanTier
from src.database.models.invitations import Invitation
from src.api.invitation.requests import (
    InvitationAcceptRequest,
    InvitationDeclineRequest,
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
async def test_get_user_pending_invitations_success(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test successful retrieval of pending invitations."""
    # Create an invitation for the test user's email
    invitation = create_test_invitation(
        organization_id=test_organization.id,
        email="test@example.com",  # Same as test user's email
    )
    db_session.add(invitation)
    await db_session.commit()

    response = await authorized_client.get("/v1/invitations/pending")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    invitations = data["data"]
    assert isinstance(invitations, list)
    assert len(invitations) >= 1

    # Find the created invitation
    created_invitation = None
    for inv in invitations:
        if inv["email"] == "test@example.com":
            created_invitation = inv
            break

    assert created_invitation is not None
    assert created_invitation["status"] == "pending"
    assert "organization_id" in created_invitation
    assert "id" in created_invitation
    assert "invited_by_id" in created_invitation
    assert "email" in created_invitation
    assert "expires_at" in created_invitation
    assert "created_at" in created_invitation
    # Token should not be exposed in API responses for security reasons
    assert "token" not in created_invitation
    # Role is not part of the invitation model
    assert "role" not in created_invitation


@pytest.mark.asyncio
async def test_get_user_pending_invitations_no_invitations(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test pending invitations when user has no invitations."""
    response = await authorized_client.get("/v1/invitations/pending")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "data" in data
    assert data["message_code"] == "success"

    invitations = data["data"]
    assert isinstance(invitations, list)
    assert len(invitations) == 0


@pytest.mark.asyncio
async def test_preview_invitation_valid_token(
    app, public_client: AsyncClient, test_organization, db_session
):
    """Test invitation preview with valid token."""
    invitation = create_test_invitation(
        organization_id=test_organization.id, email="preview@example.com"
    )
    db_session.add(invitation)
    await db_session.commit()

    response = await public_client.get(f"/v1/invitations/preview/{invitation.token}")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    preview_data = data["data"]
    assert preview_data["organization_name"] == test_organization.name
    assert preview_data["email"] == "preview@example.com"
    assert preview_data["role"] == "member"
    assert "inviter_name" in preview_data
    assert "expires_at" in preview_data


@pytest.mark.asyncio
async def test_preview_invitation_invalid_token(app, public_client: AsyncClient):
    """Test invitation preview with invalid token."""
    response = await public_client.get("/v1/invitations/preview/invalid_token")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_accept_invitation_success(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test successful invitation acceptance."""
    invitation = create_test_invitation(
        organization_id=test_organization.id, email="test@example.com"
    )
    db_session.add(invitation)
    await db_session.commit()

    accept_data = InvitationAcceptRequest(token=invitation.token)

    response = await authorized_client.post(
        "/v1/invitations/accept", json=accept_data.model_dump()
    )

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    accept_result = data["data"]
    assert accept_result["organization_name"] == test_organization.name
    assert "user_id" in accept_result

    # Verify the invitation status was updated
    await db_session.refresh(invitation)
    assert invitation.status == "accepted"


@pytest.mark.asyncio
async def test_accept_invitation_invalid_token(app, authorized_client: AsyncClient):
    """Test accepting invitation with invalid token."""
    accept_data = InvitationAcceptRequest(token="invalid_token")

    response = await authorized_client.post(
        "/v1/invitations/accept", json=accept_data.model_dump()
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_accept_invitation_already_accepted(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test accepting already accepted invitation."""
    invitation = create_test_invitation(
        organization_id=test_organization.id, email="test@example.com"
    )
    invitation.status = "accepted"
    db_session.add(invitation)
    await db_session.commit()

    accept_data = InvitationAcceptRequest(token=invitation.token)

    response = await authorized_client.post(
        "/v1/invitations/accept", json=accept_data.model_dump()
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_decline_invitation_success(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test successful invitation decline."""
    invitation = create_test_invitation(
        organization_id=test_organization.id, email="test@example.com"
    )
    db_session.add(invitation)
    await db_session.commit()

    decline_data = InvitationDeclineRequest(token=invitation.token)

    response = await authorized_client.post(
        "/v1/invitations/decline", json=decline_data.model_dump()
    )

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "message" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    # Verify the invitation status was updated
    await db_session.refresh(invitation)
    assert invitation.status == "declined"


@pytest.mark.asyncio
async def test_decline_invitation_invalid_token(app, authorized_client: AsyncClient):
    """Test declining invitation with invalid token."""
    decline_data = InvitationDeclineRequest(token="invalid_token")

    response = await authorized_client.post(
        "/v1/invitations/decline", json=decline_data.model_dump()
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_multiple_invitations_handling(
    app, authorized_client: AsyncClient, test_organization, db_session
):
    """Test handling multiple invitations for the same user."""
    # Create multiple invitations for the test user
    invitations = []
    for i in range(3):
        invitation = create_test_invitation(
            organization_id=test_organization.id, email="test@example.com"
        )
        invitations.append(invitation)
        db_session.add(invitation)
    await db_session.commit()

    # Check pending invitations
    response = await authorized_client.get("/v1/invitations/pending")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    pending_invitations = data["data"]
    assert len(pending_invitations) >= 3

    # Accept first invitation
    accept_data = InvitationAcceptRequest(token=invitations[0].token)
    accept_response = await authorized_client.post(
        "/v1/invitations/accept", json=accept_data.model_dump()
    )

    assert accept_response.status_code == status.HTTP_200_OK

    # Verify first invitation was accepted
    await db_session.refresh(invitations[0])
    assert invitations[0].status == "accepted"

    # Check pending invitations again
    response2 = await authorized_client.get("/v1/invitations/pending")

    assert response2.status_code == status.HTTP_200_OK

    data2 = response2.json()
    pending_invitations2 = data2["data"]
    assert len(pending_invitations2) >= 2  # Should still have remaining invitations


@pytest.mark.asyncio
async def test_invitation_token_security(
    app,
    public_client: AsyncClient,
    authorized_client: AsyncClient,
    test_organization,
    db_session,
):
    """Test invitation token security and validation."""
    invitation = create_test_invitation(
        organization_id=test_organization.id, email="security@example.com"
    )
    db_session.add(invitation)
    await db_session.commit()

    # Test preview with valid token
    valid_preview = await public_client.get(
        f"/v1/invitations/preview/{invitation.token}"
    )
    assert valid_preview.status_code == status.HTTP_200_OK

    # Test preview with invalid token
    invalid_preview = await public_client.get("/v1/invitations/preview/invalid_token")
    assert invalid_preview.status_code == status.HTTP_404_NOT_FOUND

    # Test accept with invalid token
    invalid_accept = InvitationAcceptRequest(token="invalid_token")
    invalid_accept_response = await authorized_client.post(
        "/v1/invitations/accept", json=invalid_accept.model_dump()
    )
    assert invalid_accept_response.status_code == status.HTTP_400_BAD_REQUEST

    # Test decline with invalid token
    invalid_decline = InvitationDeclineRequest(token="invalid_token")
    invalid_decline_response = await authorized_client.post(
        "/v1/invitations/decline", json=invalid_decline.model_dump()
    )
    assert invalid_decline_response.status_code == status.HTTP_400_BAD_REQUEST

    # Test accept with valid token
    valid_accept = InvitationAcceptRequest(token=invitation.token)
    valid_accept_response = await authorized_client.post(
        "/v1/invitations/accept", json=valid_accept.model_dump()
    )
    assert valid_accept_response.status_code == status.HTTP_200_OK
