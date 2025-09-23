"""Invitation domain requests and responses."""

from pydantic import BaseModel, EmailStr, Field

from src.api.core.messages import APIResponse
from .models import InvitationModel


# Request Models
class InvitationCreateRequest(BaseModel):
    """Request for creating an invitation."""

    email: EmailStr
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InvitationListRequest(BaseModel):
    """Request for listing invitations with pagination."""

    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class InvitationAcceptRequest(BaseModel):
    """Request for accepting an invitation."""

    token: str


class InvitationDeclineRequest(BaseModel):
    """Request for declining an invitation."""

    token: str


# Response Types (using generic APIResponse)
InvitationCreateResponse = APIResponse[InvitationModel]
InvitationAcceptResponse = APIResponse[InvitationModel]
InvitationDeclineResponse = APIResponse[InvitationModel]
InvitationListResponse = APIResponse[list[InvitationModel]]
InvitationPreviewResponse = APIResponse[dict]
