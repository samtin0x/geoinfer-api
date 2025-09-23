"""User domain requests and responses."""

from pydantic import BaseModel, Field

from src.api.core.messages import APIResponse
from .models import UserOrganizationModel, UserModel


# Request Models
class UserProfileUpdateRequest(BaseModel):
    """Request for updating user profile."""

    name: str | None = Field(None, min_length=1, max_length=100)


# Response Models
class UserOrganizationsResponse(APIResponse[list[UserOrganizationModel]]):
    """Response for listing user organizations."""


UserProfileResponse = APIResponse[UserModel]
