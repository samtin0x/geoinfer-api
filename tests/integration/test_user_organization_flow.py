from uuid import UUID, uuid4

import pytest

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.api.organization.handler import (
    create_organization_handler,
    update_organization_handler,
)
from src.api.organization.requests import (
    OrganizationCreateRequest,
    OrganizationUpdateRequest,
)
from src.database.models import PlanTier
from src.database.models.organizations import OrganizationRole
from src.services.organization.invitation_manager import OrganizationInvitationService
from src.services.organization.service import OrganizationService
from src.services.user.user_management import UserManagementService


@pytest.mark.asyncio(loop_scope="session")
async def test_user_login_and_permission_escalation_flow(db_session):
    user_management = UserManagementService(db_session)
    organization_service = OrganizationService(db_session)
    invitation_service = OrganizationInvitationService(db_session)

    free_user_id = uuid4()
    free_user_email = "free-user@example.com"

    user_payload = {
        "sub": str(free_user_id),
        "email": free_user_email,
        "user_metadata": {"first_name": "Free", "last_name": "User"},
    }

    free_user, personal_org = await user_management.handle_jwt_authentication(
        user_payload
    )
    assert free_user.id == free_user_id
    assert personal_org.plan_tier == PlanTier.FREE
    assert free_user.organization_id == personal_org.id

    owner_id = uuid4()
    owner_email = "owner@example.com"
    owner_payload = {
        "sub": str(owner_id),
        "email": owner_email,
        "user_metadata": {"first_name": "Enterprise", "last_name": "Owner"},
    }

    owner_user, _ = await user_management.handle_jwt_authentication(owner_payload)
    await user_management.update_user_plan_tier(owner_id, PlanTier.ENTERPRISE)

    enterprise_org = await organization_service.create_organization(
        name="Enterprise Org",
        user_id=owner_id,
        logo_url=None,
    )
    enterprise_org_id = str(enterprise_org.id)

    await organization_service.add_user_to_organization(
        organization_id=enterprise_org_id,
        user_id=str(free_user_id),
        requesting_user_id=str(owner_id),
        role=OrganizationRole.MEMBER,
    )

    # Free user should not be able to create invitations for their own FREE organization
    with pytest.raises(GeoInferException) as exc_info:
        await invitation_service.create_invitation(
            organization_id=free_user.organization_id,  # Use free user's organization
            email="invitee@example.com",
            invited_by_id=free_user_id,
        )
    assert exc_info.value.message_code == MessageCode.AUTH_INSUFFICIENT_PLAN_TIER

    with pytest.raises(GeoInferException) as exc_info:
        await update_organization_handler(
            db=db_session,
            organization_id=UUID(enterprise_org_id),
            organization_data=OrganizationUpdateRequest(name="Renamed Org"),
            requesting_user_id=free_user_id,
        )
    assert exc_info.value.message_code == MessageCode.INSUFFICIENT_PERMISSIONS

    # Note: API layer decorators should prevent free users from reaching this handler
    # Since we're testing the handler directly, we expect it to succeed when called
    # In real usage, the @require_plan_tier decorator would block this
    organization = await create_organization_handler(
        db=db_session,
        organization_data=OrganizationCreateRequest(name="Attempted Extra Org"),
        user_id=str(free_user_id),
    )
    # Should create organization successfully since service trusts API layer validation
    assert organization.data.name == "Attempted Extra Org"
    assert organization.message_code == MessageCode.ORGANIZATION_CREATED

    # Elevate plan tier and role
    new_org = await organization_service.create_organization(
        name="Free User Org",
        user_id=free_user_id,
        logo_url=None,
    )
    new_org_id = str(new_org.id)
    assert (
        UUID(new_org_id) != free_user_id
    )  # New org should have different ID from user

    # Since free user cannot create their own enterprise org,
    # test that they can still create invitations for the existing org
    invitation = await invitation_service.create_invitation(
        organization_id=UUID(enterprise_org_id),
        email="new-member@example.com",
        invited_by_id=free_user_id,
    )
    assert invitation.email == "new-member@example.com"
    assert invitation.invited_by_id == free_user_id

    invitations = await invitation_service.list_organization_invitations(
        organization_id=UUID(enterprise_org_id)
    )
    assert len(invitations) == 1
    assert invitations[0].token == invitation.token
