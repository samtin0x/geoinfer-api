"""User API schemas (combined models/requests)."""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field
from src.api.core.messages import APIResponse


class UserOrganizationModel(BaseModel):
    id: UUID
    name: str
    logo_url: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {datetime: lambda v: v.isoformat()}


class UserModel(BaseModel):
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


class UserProfileUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)


class SetActiveOrganizationRequest(BaseModel):
    organization_id: UUID


class UserOrganizationsResponse(APIResponse[list[UserOrganizationModel]]):
    pass


UserProfileResponse = APIResponse[UserModel]
SetActiveOrganizationResponse = APIResponse[bool]
