"""Role API schemas (combined models/requests)."""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel
from src.api.core.messages import APIResponse
from src.database.models import OrganizationRole


class UserOrganizationRoleModel(BaseModel):
    id: UUID
    user_id: UUID
    organization_id: UUID
    role: OrganizationRole
    granted_by_id: UUID
    granted_at: datetime

    model_config = {"from_attributes": True}


class RoleDefinitionData(BaseModel):
    role: str
    permissions: list[str]


class RoleDefinitionsData(BaseModel):
    roles: list[RoleDefinitionData]
    all_permissions: list[str]


class RoleManagementData(BaseModel):
    message: str


class GrantRoleRequest(BaseModel):
    role: OrganizationRole


class RevokeRoleRequest(BaseModel):
    role: OrganizationRole


class ChangeRoleRequest(BaseModel):
    role: OrganizationRole


UserRoleResponse = APIResponse[UserOrganizationRoleModel]
RoleChangeResponse = APIResponse[bool]
RoleManagementResponse = APIResponse[RoleManagementData]
CurrentUserRolesResponse = APIResponse[list[UserOrganizationRoleModel]]
OrganizationRoleListResponse = APIResponse[RoleDefinitionsData]
