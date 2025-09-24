"""Organization API schemas (combined models/requests)."""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, HttpUrl
from src.api.core.messages import APIResponse


class OrganizationModel(BaseModel):
    id: UUID
    name: str
    logo_url: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {datetime: lambda v: v.isoformat()}


class OrganizationCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    logo_url: str | None = None


class OrganizationUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    logo_url: HttpUrl | None = None


class RemoveUserRequest(BaseModel):
    user_id: UUID


class UserWithRoleData(BaseModel):
    user_id: str
    name: str
    email: str
    role: str


class OrganizationUsersData(BaseModel):
    organization_id: str
    users: list[UserWithRoleData]
    user_count: int


OrganizationCreateResponse = APIResponse[OrganizationModel]
OrganizationUpdateResponse = APIResponse[OrganizationModel]
RemoveUserResponse = APIResponse[bool]
OrganizationUsersResponse = APIResponse[OrganizationUsersData]
