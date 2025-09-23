"""Invitation domain handlers."""

from uuid import UUID


from src.api.core.messages import APIResponse, MessageCode
from src.services.organization.invitation_manager import OrganizationInvitationService
from .models import InvitationModel, InvitationWithDetailsModel
from .requests import (
    InvitationCreateRequest,
    InvitationCreateResponse,
    InvitationAcceptRequest,
    InvitationAcceptResponse,
    InvitationDeclineRequest,
    InvitationDeclineResponse,
    InvitationListResponse,
    InvitationPreviewResponse,
)


async def create_invitation_handler(
    invitation_service: OrganizationInvitationService,
    organization_id: UUID,
    invitation_data: InvitationCreateRequest,
    requesting_user_id: UUID,
) -> InvitationCreateResponse:
    """Create a new organization invitation."""

    invitation = await invitation_service.create_invitation(
        organization_id=organization_id,
        email=invitation_data.email,
        invited_by_id=requesting_user_id,
        expires_in_days=invitation_data.expires_in_days,
    )

    return APIResponse.success(
        message_code=MessageCode.INVITE_CREATED,
        data=InvitationModel.model_validate(invitation),
    )


async def list_organization_invitations_handler(
    invitation_service: OrganizationInvitationService,
    organization_id: UUID,
    requesting_user_id: UUID,
) -> InvitationListResponse:
    """List all invitations for an organization."""

    invitations = await invitation_service.list_organization_invitations(
        organization_id=organization_id,
        requesting_user_id=requesting_user_id,
    )

    invitation_data = [
        InvitationModel.model_validate(invitation) for invitation in invitations
    ]

    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data=invitation_data,
    )


async def get_user_pending_invitations_handler(
    invitation_service: OrganizationInvitationService,
    requesting_user_id: UUID,
) -> InvitationListResponse:
    """Get all pending invitations for the current user."""
    # Get user to extract email
    from src.database.models import User

    user = await invitation_service.db.get(User, requesting_user_id)
    if not user:
        from src.api.core.exceptions.base import GeoInferException
        from fastapi import status

        raise GeoInferException(MessageCode.USER_NOT_FOUND, status.HTTP_404_NOT_FOUND)

    invitations = await invitation_service.get_user_pending_invitations(
        user_email=user.email
    )

    invitation_data = [
        InvitationModel.model_validate(invitation) for invitation in invitations
    ]

    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data=invitation_data,
    )


async def accept_invitation_handler(
    invitation_service: OrganizationInvitationService,
    invitation_data: InvitationAcceptRequest,
    requesting_user_id: UUID,
) -> InvitationAcceptResponse:
    """Accept an organization invitation."""

    invitation = await invitation_service.respond_to_invitation(
        token=invitation_data.token,
        user_id=requesting_user_id,
        accept=True,
    )

    return APIResponse.success(
        message_code=MessageCode.INVITE_ACCEPTED,
        data=InvitationModel.model_validate(invitation),
    )


async def decline_invitation_handler(
    invitation_service: OrganizationInvitationService,
    invitation_data: InvitationDeclineRequest,
    requesting_user_id: UUID,
) -> InvitationDeclineResponse:
    """Decline an organization invitation."""

    invitation = await invitation_service.respond_to_invitation(
        token=invitation_data.token,
        user_id=requesting_user_id,
        accept=False,
    )

    return APIResponse.success(
        message_code=MessageCode.INVITE_DECLINED,
        data=InvitationModel.model_validate(invitation),
    )


async def cancel_invitation_handler(
    invitation_service: OrganizationInvitationService,
    invitation_id: UUID,
    requesting_user_id: UUID,
) -> InvitationAcceptResponse:
    """Cancel an organization invitation."""

    invitation = await invitation_service.cancel_invitation(
        invitation_id=invitation_id,
        requesting_user_id=requesting_user_id,
    )

    return APIResponse.success(
        message_code=MessageCode.DELETED,
        data=InvitationModel.model_validate(invitation),
    )


async def preview_invitation_handler(
    invitation_service: OrganizationInvitationService,
    token: str,
) -> InvitationPreviewResponse:
    """Preview invitation details without accepting it."""

    # Get invitation by token
    from sqlalchemy import select
    from src.database.models import Invitation
    from sqlalchemy.orm import selectinload

    stmt = (
        select(Invitation)
        .options(
            selectinload(Invitation.organization),
            selectinload(Invitation.invited_by),
        )
        .where(Invitation.token == token)
    )
    result = await invitation_service.db.execute(stmt)
    invitation = result.scalar_one_or_none()

    if not invitation:
        from src.api.core.exceptions.base import GeoInferException
        from fastapi import status

        raise GeoInferException(MessageCode.INVITE_NOT_FOUND, status.HTTP_404_NOT_FOUND)

    # Check if invitation can be responded to
    await invitation_service._ensure_invitation_can_be_responded(invitation)

    invitation_data = InvitationWithDetailsModel.model_validate(invitation)

    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data={
            "organization_name": invitation_data.organization.name,
            "organization_logo": bool(invitation_data.organization.logo_url),
            "invited_by_name": invitation_data.invited_by.name,
            "invited_by_email": invitation_data.invited_by.email,
            "can_accept": True,
        },
    )
