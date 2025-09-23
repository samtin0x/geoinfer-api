"""Invitation domain router."""

from uuid import UUID

from fastapi import APIRouter, Request

from src.api.core.decorators.auth import require_permission, require_plan_tier
from src.api.core.dependencies import (
    AsyncSessionDep,
    CurrentUserAuthDep,
    OrganizationInvitationServiceDep,
)
from src.database.models.organizations import OrganizationPermission, PlanTier
from .handler import (
    accept_invitation_handler,
    cancel_invitation_handler,
    create_invitation_handler,
    decline_invitation_handler,
    list_organization_invitations_handler,
    get_user_pending_invitations_handler,
    preview_invitation_handler,
)
from .requests import (
    InvitationAcceptRequest,
    InvitationAcceptResponse,
    InvitationCreateRequest,
    InvitationCreateResponse,
    InvitationDeclineRequest,
    InvitationDeclineResponse,
    InvitationListResponse,
    InvitationPreviewResponse,
)

router = APIRouter(
    prefix="/invitations",
    tags=["invitations"],
)


@router.get("/pending", response_model=InvitationListResponse)
async def get_user_pending_invitations(
    request: Request,
    invitation_service: OrganizationInvitationServiceDep,
    current_user: CurrentUserAuthDep,
) -> InvitationListResponse:
    """Get all pending invitations for the current user."""
    return await get_user_pending_invitations_handler(
        invitation_service=invitation_service,
        requesting_user_id=current_user.user.id,
    )


@router.get("/preview/{token}", response_model=InvitationPreviewResponse)
async def preview_invitation(
    token: str,
    request: Request,
    invitation_service: OrganizationInvitationServiceDep,
) -> InvitationPreviewResponse:
    """Preview invitation details without accepting it."""
    return await preview_invitation_handler(
        invitation_service=invitation_service,
        token=token,
    )


@router.post("/accept", response_model=InvitationAcceptResponse)
async def accept_invitation(
    request: Request,
    invitation_data: InvitationAcceptRequest,
    invitation_service: OrganizationInvitationServiceDep,
    current_user: CurrentUserAuthDep,
) -> InvitationAcceptResponse:
    """Accept an organization invitation."""
    return await accept_invitation_handler(
        invitation_service=invitation_service,
        invitation_data=invitation_data,
        requesting_user_id=current_user.user.id,
    )


@router.post("/decline", response_model=InvitationDeclineResponse)
async def decline_invitation(
    request: Request,
    invitation_data: InvitationDeclineRequest,
    invitation_service: OrganizationInvitationServiceDep,
    current_user: CurrentUserAuthDep,
) -> InvitationDeclineResponse:
    """Decline an organization invitation."""
    return await decline_invitation_handler(
        invitation_service=invitation_service,
        invitation_data=invitation_data,
        requesting_user_id=current_user.user.id,
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
    organization_id = current_user.organization.id
    return await create_invitation_handler(
        invitation_service=invitation_service,
        organization_id=organization_id,
        invitation_data=invitation_data,
        requesting_user_id=current_user.user.id,
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
    return await cancel_invitation_handler(
        invitation_service=invitation_service,
        invitation_id=invitation_id,
        requesting_user_id=current_user.user.id,
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
    organization_id = current_user.organization.id
    return await list_organization_invitations_handler(
        invitation_service=invitation_service,
        organization_id=organization_id,
        requesting_user_id=current_user.user.id,
    )
