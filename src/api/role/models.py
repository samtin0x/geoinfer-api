"""Role domain models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from src.database.models import OrganizationRole


class UserOrganizationRoleModel(BaseModel):
    """User organization role API model."""

    id: UUID
    user_id: UUID
    organization_id: UUID
    role: OrganizationRole
    granted_by_id: UUID
    granted_at: datetime

    model_config = {"from_attributes": True}


class UserWithRoleData(BaseModel):
    """User data with their role in organization."""

    user_id: str
    name: str
    email: str
    role: str


class OrganizationUsersRoleData(BaseModel):
    """Organization users with their roles."""

    organization_id: str
    users: list[UserWithRoleData]
    user_count: int


class RoleDefinitionData(BaseModel):
    """Role definition with permissions."""

    role: str
    permissions: list[str]


class RoleDefinitionsData(BaseModel):
    """All role definitions and permissions."""

    roles: list[RoleDefinitionData]
    all_permissions: list[str]


class RoleManagementData(BaseModel):
    """Simple message response for role management operations."""

    message: str
