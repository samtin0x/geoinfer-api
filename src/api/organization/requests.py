from uuid import UUID
from pydantic import BaseModel, Field, HttpUrl

from src.api.core.messages import APIResponse
from .models import OrganizationModel


class OrganizationCreateRequest(BaseModel):
    """Request for creating an organization."""

    name: str = Field(..., min_length=1, max_length=100)
    logo_url: HttpUrl | None = None


class OrganizationUpdateRequest(BaseModel):
    """Request for updating an organization."""

    name: str | None = Field(None, min_length=1, max_length=100)
    logo_url: HttpUrl | None = None


# Request Models
class RemoveUserRequest(BaseModel):
    """Request for removing a user from an organization."""

    user_id: UUID


# Response Types (using generic APIResponse)
OrganizationCreateResponse = APIResponse[OrganizationModel]
OrganizationUpdateResponse = APIResponse[OrganizationModel]
RemoveUserResponse = APIResponse[dict]
