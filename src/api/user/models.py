"""User domain models."""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr


class UserOrganizationModel(BaseModel):
    """Core organization info for user organization switching."""

    id: UUID
    name: str
    logo_url: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {datetime: lambda v: v.isoformat()}


class UserModel(BaseModel):
    """User information and profile."""

    id: UUID
    name: str
    email: EmailStr
    plan_tier: str | None = None
    organization_id: UUID | None = None
    organization_name: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {datetime: lambda v: v.isoformat()}
