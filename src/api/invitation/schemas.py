"""Invitation API schemas (combined models/requests)."""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field
from src.api.core.messages import APIResponse
from src.api.user.schemas import UserModel
from src.api.organization.schemas import OrganizationModel


class InvitationModel(BaseModel):
    id: UUID
    organization_id: UUID
    invited_by_id: UUID
    email: str
    status: str
    expires_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {datetime: lambda v: v.isoformat()}


class InvitationWithDetailsModel(InvitationModel):
    organization: OrganizationModel
    invited_by: UserModel
    email: str

    class Config:
        from_attributes = True


class InvitationCreateRequest(BaseModel):
    email: EmailStr
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InvitationListRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class InvitationAcceptRequest(BaseModel):
    token: str


class InvitationDeclineRequest(BaseModel):
    token: str


InvitationCreateResponse = APIResponse[InvitationModel]
InvitationAcceptResponse = APIResponse[InvitationModel]
InvitationDeclineResponse = APIResponse[InvitationModel]
InvitationListResponse = APIResponse[list[InvitationModel]]
InvitationPreviewResponse = APIResponse[dict]
