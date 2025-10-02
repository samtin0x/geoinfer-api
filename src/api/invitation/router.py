"""Invitation domain router."""

from uuid import UUID

from fastapi import APIRouter, Request

from src.api.core.decorators.auth import require_permission, require_plan_tier
from src.api.core.dependencies import (
    AsyncSessionDep,
    CurrentUserAuthDep,
    OrganizationInvitationServiceDep,
)
from src.api.core.messages import APIResponse, MessageCode
from src.database.models.organizations import OrganizationPermission, PlanTier
from src.api.invitation.schemas import (
    InvitationAcceptRequest,
    InvitationAcceptResponse,
    InvitationCreateRequest,
    InvitationCreateResponse,
    InvitationDeclineRequest,
    InvitationDeclineResponse,
    InvitationListResponse,
    InvitationModel,
    InvitationPreviewResponse,
    InvitationWithDetailsListResponse,
    InvitationWithDetailsModel,
)

router = APIRouter(
    prefix="/invitations",
    tags=["invitations"],
)


@router.get("/pending", response_model=InvitationWithDetailsListResponse)
async def get_user_pending_invitations(
    request: Request,
    invitation_service: OrganizationInvitationServiceDep,
    current_user: CurrentUserAuthDep,
) -> InvitationWithDetailsListResponse:
    """Get all pending invitations for the current user."""
    invitations = await invitation_service.get_user_pending_invitations(
        user_email=current_user.user.email
    )
    invitation_data = [
        InvitationWithDetailsModel.model_validate(invitation)
        for invitation in invitations
    ]
    return APIResponse.success(message_code=MessageCode.SUCCESS, data=invitation_data)


@router.get("/preview/{token}", response_model=InvitationPreviewResponse)
async def preview_invitation(
    token: str,
    request: Request,
    invitation_service: OrganizationInvitationServiceDep,
) -> InvitationPreviewResponse:
    """Preview invitation details without accepting it."""
    preview_data = await invitation_service.preview_invitation(token)
    return APIResponse.success(message_code=MessageCode.SUCCESS, data=preview_data)


@router.post("/accept", response_model=InvitationAcceptResponse)
async def accept_invitation(
    request: Request,
    invitation_data: InvitationAcceptRequest,
    invitation_service: OrganizationInvitationServiceDep,
    current_user: CurrentUserAuthDep,
) -> InvitationAcceptResponse:
    """Accept an organization invitation."""
    invitation = await invitation_service.respond_to_invitation(
        token=invitation_data.token, user_id=current_user.user.id, accept=True
    )
    return APIResponse.success(
        message_code=MessageCode.INVITE_ACCEPTED,
        data=InvitationModel.model_validate(invitation),
    )


@router.post("/decline", response_model=InvitationDeclineResponse)
async def decline_invitation(
    request: Request,
    invitation_data: InvitationDeclineRequest,
    invitation_service: OrganizationInvitationServiceDep,
    current_user: CurrentUserAuthDep,
) -> InvitationDeclineResponse:
    """Decline an organization invitation."""
    invitation = await invitation_service.respond_to_invitation(
        token=invitation_data.token, user_id=current_user.user.id, accept=False
    )
    return APIResponse.success(
        message_code=MessageCode.INVITE_DECLINED,
        data=InvitationModel.model_validate(invitation),
    )


@router.post("/", response_model=InvitationCreateResponse)
@require_plan_tier([PlanTier.ENTERPRISE])
@require_permission(OrganizationPermission.MANAGE_MEMBERS)
async def create_invitation(
    request: Request,
    invitation_data: InvitationCreateRequest,
    db: AsyncSessionDep,
    invitation_service: OrganizationInvitationServiceDep,
    current_user: CurrentUserAuthDep,
) -> InvitationCreateResponse:
    """Create a new organization invitation."""
    invitation = await invitation_service.create_invitation(
        organization_id=current_user.organization.id,
        email=invitation_data.email,
        invited_by_id=current_user.user.id,
        expires_in_days=invitation_data.expires_in_days,
    )
    return APIResponse.success(
        message_code=MessageCode.INVITE_CREATED,
        data=InvitationModel.model_validate(invitation),
    )


@router.delete("/{invitation_id}", response_model=InvitationAcceptResponse)
@require_plan_tier([PlanTier.ENTERPRISE])
@require_permission(OrganizationPermission.MANAGE_MEMBERS)
async def cancel_invitation(
    invitation_id: UUID,
    request: Request,
    db: AsyncSessionDep,
    invitation_service: OrganizationInvitationServiceDep,
    current_user: CurrentUserAuthDep,
) -> InvitationAcceptResponse:
    """Cancel an organization invitation."""
    invitation = await invitation_service.cancel_invitation(
        invitation_id=invitation_id, requesting_user_id=current_user.user.id
    )
    return APIResponse.success(
        message_code=MessageCode.DELETED,
        data=InvitationModel.model_validate(invitation),
    )


@router.get("/list", response_model=InvitationListResponse)
@require_plan_tier([PlanTier.ENTERPRISE])
@require_permission(OrganizationPermission.MANAGE_MEMBERS)
async def list_organization_invitations(
    request: Request,
    db: AsyncSessionDep,
    invitation_service: OrganizationInvitationServiceDep,
    current_user: CurrentUserAuthDep,
) -> InvitationListResponse:
    """List all invitations for the current user's organization (enterprise only)."""
    invitations = await invitation_service.list_organization_invitations(
        organization_id=current_user.organization.id,
        requesting_user_id=current_user.user.id,
    )
    invitation_data = [
        InvitationModel.model_validate(invitation) for invitation in invitations
    ]
    return APIResponse.success(message_code=MessageCode.SUCCESS, data=invitation_data)
