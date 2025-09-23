from datetime import datetime
from uuid import UUID
from pydantic import BaseModel

from src.api.user.models import UserModel
from src.api.organization.models import OrganizationModel


class InvitationModel(BaseModel):
    """Core invitation model."""

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
    """Invitation model with organization and user details."""

    organization: OrganizationModel
    invited_by: UserModel
    email: str

    class Config:
        from_attributes = True
