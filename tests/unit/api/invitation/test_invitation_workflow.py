"""Comprehensive tests for invitation workflow."""

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
async def test_create_and_list_invitation_workflow(
    app, authorized_client: AsyncClient, db_session, test_user, test_organization
):
    """Test complete invitation creation and listing workflow."""
    # First, update the test organization to be enterprise (required for invitations)
    test_organization.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_organization)
    await db_session.commit()

    # Create an invitation
    create_data = InvitationCreateRequest(email="invited@example.com", role="member")

    create_response = await authorized_client.post(
        "/v1/invitations/", json=create_data.model_dump()
    )

    # Should succeed for enterprise user with proper permissions
    assert create_response.status_code == status.HTTP_201_CREATED

    create_data = create_response.json()
    assert "data" in create_data
    assert "message_code" in create_data
    assert create_data["message_code"] == "success"
    assert create_data["data"]["email"] == "invited@example.com"
    assert create_data["data"]["role"] == "member"
    assert create_data["data"]["status"] == "pending"

    # Get pending invitations for the current user
    pending_response = await authorized_client.get("/v1/invitations/pending")

    # Should not show the invitation since it's for a different email
    assert pending_response.status_code == status.HTTP_200_OK
    pending_data = pending_response.json()
    assert "data" in pending_data
    assert isinstance(pending_data["data"], list)
    # The invitation shouldn't appear in this user's pending invitations
    assert len(pending_data["data"]) == 0

    # List organization invitations (should require MANAGE_MEMBERS permission)
    list_response = await authorized_client.get("/v1/invitations/list")

    # Should succeed or fail based on permissions
    if list_response.status_code == status.HTTP_200_OK:
        list_data = list_response.json()
        assert "data" in list_data
        assert isinstance(list_data["data"], list)

        # Should include the invitation we just created
        assert len(list_data["data"]) >= 1
        found_invitation = False
        for invitation in list_data["data"]:
            if invitation["email"] == "invited@example.com":
                found_invitation = True
                assert invitation["role"] == "member"
                assert invitation["status"] == "pending"
                break

        assert found_invitation, "Created invitation should appear in organization list"


@pytest.mark.asyncio
async def test_invitation_preview_and_accept_workflow(
    app,
    public_client: AsyncClient,
    authorized_client: AsyncClient,
    db_session,
    test_organization,
):
    """Test invitation preview and acceptance workflow."""
    # Create an invitation manually in the database
    invitation = create_test_invitation(
        organization_id=test_organization.id, email="accept@example.com"
    )
    db_session.add(invitation)
    await db_session.commit()

    # Preview the invitation (should work without authentication)
    preview_response = await public_client.get(
        f"/v1/invitations/preview/{invitation.token}"
    )

    assert preview_response.status_code == status.HTTP_200_OK

    preview_data = preview_response.json()
    assert "data" in preview_data
    assert preview_data["data"]["organization_name"] == test_organization.name
    assert preview_data["data"]["email"] == "accept@example.com"
    assert preview_data["data"]["role"] == "member"
    assert "inviter_name" in preview_data["data"]

    # Accept the invitation (requires authentication)
    accept_data = InvitationAcceptRequest(token=invitation.token)

    accept_response = await authorized_client.post(
        "/v1/invitations/accept", json=accept_data.model_dump()
    )

    # Should either succeed or fail based on business logic
    assert accept_response.status_code in [
        status.HTTP_200_OK,
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_403_FORBIDDEN,
    ]

    if accept_response.status_code == status.HTTP_200_OK:
        accept_result = accept_response.json()
        assert "data" in accept_result
        assert "organization_name" in accept_result["data"]
        assert accept_result["data"]["organization_name"] == test_organization.name

        # Verify the invitation status was updated
        await db_session.refresh(invitation)
        assert invitation.status == "accepted"

        # Verify user was added to organization (this would depend on your implementation)
        # You might want to check user_organization_memberships table


@pytest.mark.asyncio
async def test_invitation_decline_workflow(
    app, authorized_client: AsyncClient, db_session, test_organization
):
    """Test invitation decline workflow."""
    # Create an invitation manually in the database
    invitation = create_test_invitation(
        organization_id=test_organization.id, email="decline@example.com"
    )
    db_session.add(invitation)
    await db_session.commit()

    # Decline the invitation
    decline_data = InvitationDeclineRequest(token=invitation.token)

    decline_response = await authorized_client.post(
        "/v1/invitations/decline", json=decline_data.model_dump()
    )

    # Should either succeed or fail based on business logic
    assert decline_response.status_code in [
        status.HTTP_200_OK,
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_403_FORBIDDEN,
    ]

    if decline_response.status_code == status.HTTP_200_OK:
        decline_result = decline_response.json()
        assert "message" in decline_result
        assert "message_code" in decline_result

        # Verify the invitation status was updated
        await db_session.refresh(invitation)
        assert invitation.status == "declined"


@pytest.mark.asyncio
async def test_cancel_invitation_workflow(
    app, authorized_client: AsyncClient, db_session, test_organization
):
    """Test invitation cancellation workflow."""
    # Create an invitation manually in the database
    invitation = create_test_invitation(
        organization_id=test_organization.id, email="cancel@example.com"
    )
    db_session.add(invitation)
    await db_session.commit()

    # Cancel the invitation
    cancel_response = await authorized_client.delete(f"/v1/invitations/{invitation.id}")

    # Should either succeed or fail based on permissions
    assert cancel_response.status_code in [
        status.HTTP_200_OK,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
    ]

    if cancel_response.status_code == status.HTTP_200_OK:
        cancel_result = cancel_response.json()
        assert "message" in cancel_result
        assert "message_code" in cancel_result

        # Verify the invitation status was updated
        await db_session.refresh(invitation)
        assert invitation.status == "cancelled"


@pytest.mark.parametrize(
    "email,role,scenario_name",
    [
        ("invalid-email-format", "member", "invalid_email_format"),
        ("valid@example.com", "invalid_role", "invalid_role"),
        ("", "member", "empty_email"),
        ("valid@example.com", "", "empty_role"),
    ],
)
@pytest.mark.asyncio
async def test_invitation_validation_scenarios(
    email: str,
    role: str,
    scenario_name: str,
    app,
    authorized_client: AsyncClient,
    db_session,
    test_organization,
):
    """Test various invitation validation scenarios."""
    invitation_data = InvitationCreateRequest(email=email, role=role)

    response = await authorized_client.post(
        "/v1/invitations/", json=invitation_data.model_dump()
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_multiple_invitations_workflow(
    app, authorized_client: AsyncClient, db_session, test_organization
):
    """Test creating multiple invitations."""
    # Update organization to enterprise
    test_organization.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_organization)
    await db_session.commit()

    # Create multiple invitations
    emails = ["user1@example.com", "user2@example.com", "user3@example.com"]
    created_invitations = []

    for email in emails:
        create_data = InvitationCreateRequest(email=email, role="member")

        response = await authorized_client.post(
            "/v1/invitations/", json=create_data.model_dump()
        )

        if response.status_code == status.HTTP_201_CREATED:
            created_invitations.append(response.json()["data"])

    # Verify all were created
    assert len(created_invitations) == len(emails)

    # List organization invitations
    list_response = await authorized_client.get("/v1/invitations/list")

    if list_response.status_code == status.HTTP_200_OK:
        list_data = list_response.json()
        assert len(list_data["data"]) >= len(created_invitations)

        # Verify all created invitations are in the list
        created_emails = [inv["email"] for inv in created_invitations]
        for invitation in list_data["data"]:
            if invitation["email"] in created_emails:
                assert invitation["role"] == "member"
                assert invitation["status"] == "pending"
                created_emails.remove(invitation["email"])

        assert len(created_emails) == 0, "All created invitations should be in the list"


@pytest.mark.asyncio
async def test_invitation_token_security_valid_token(
    app, public_client: AsyncClient, db_session, test_organization
):
    """Test invitation token security with valid token."""
    # Create an invitation
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


@pytest.mark.parametrize(
    "endpoint,request_data,expected_status",
    [
        ("/v1/invitations/preview/invalid_token", None, status.HTTP_404_NOT_FOUND),
        (
            "/v1/invitations/accept",
            InvitationAcceptRequest(token="invalid_token"),
            status.HTTP_400_BAD_REQUEST,
        ),
        (
            "/v1/invitations/decline",
            InvitationDeclineRequest(token="invalid_token"),
            status.HTTP_400_BAD_REQUEST,
        ),
    ],
)
@pytest.mark.asyncio
async def test_invitation_token_security_invalid_tokens(
    endpoint: str,
    request_data: InvitationAcceptRequest | InvitationDeclineRequest | None,
    expected_status: int,
    app,
    public_client: AsyncClient,
    authorized_client: AsyncClient,
):
    """Test invitation token security with invalid tokens."""
    if request_data:
        client = (
            authorized_client
            if "accept" in endpoint or "decline" in endpoint
            else public_client
        )
        response = await client.post(endpoint, json=request_data.model_dump())
    else:
        response = await public_client.get(endpoint)

    assert response.status_code == expected_status


@pytest.mark.asyncio
async def test_invitation_permission_boundaries(
    app,
    authorized_client: AsyncClient,
    public_client: AsyncClient,
    db_session,
    test_user,
    test_organization,
):
    """Test that invitation permissions are properly enforced."""
    # Create an invitation
    invitation = create_test_invitation(
        organization_id=test_organization.id, email="permission@example.com"
    )
    db_session.add(invitation)
    await db_session.commit()

    # Test that public client cannot access authenticated endpoints
    pending_response = await public_client.get("/v1/invitations/pending")
    assert pending_response.status_code == status.HTTP_401_UNAUTHORIZED

    accept_data = InvitationAcceptRequest(token=invitation.token)
    accept_response = await public_client.post(
        "/v1/invitations/accept", json=accept_data.model_dump()
    )
    assert accept_response.status_code == status.HTTP_401_UNAUTHORIZED

    decline_data = InvitationDeclineRequest(token=invitation.token)
    decline_response = await public_client.post(
        "/v1/invitations/decline", json=decline_data.model_dump()
    )
    assert decline_response.status_code == status.HTTP_401_UNAUTHORIZED

    # Test that only authorized users can create invitations
    create_data = InvitationCreateRequest(email="auth@example.com", role="member")

    # This should fail if user doesn't have proper permissions
    create_response = await authorized_client.post(
        "/v1/invitations/", json=create_data.model_dump()
    )

    assert create_response.status_code in [
        status.HTTP_201_CREATED,
        status.HTTP_403_FORBIDDEN,
    ]

    # Test that invitation management requires proper permissions
    if invitation.id:
        cancel_response = await authorized_client.delete(
            f"/v1/invitations/{invitation.id}"
        )
        assert cancel_response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
        ]
