"""Role domain requests and responses."""

from pydantic import BaseModel

from src.api.core.messages import APIResponse
from src.database.models import OrganizationRole
from .models import (
    UserOrganizationRoleModel,
    OrganizationUsersRoleData,
    RoleDefinitionsData,
    RoleManagementData,
)


# Request Models
class GrantRoleRequest(BaseModel):
    """Request for granting a role to a user."""

    role: OrganizationRole


class RevokeRoleRequest(BaseModel):
    """Request for revoking a role from a user."""

    role: OrganizationRole


class ChangeRoleRequest(BaseModel):
    """Request for changing a user's role in an organization."""

    role: OrganizationRole


UserRoleResponse = APIResponse[UserOrganizationRoleModel]
RoleManagementResponse = APIResponse[RoleManagementData]
CurrentUserRolesResponse = APIResponse[list[UserOrganizationRoleModel]]

OrganizationUsersRoleListResponse = APIResponse[OrganizationUsersRoleData]
OrganizationRoleListResponse = APIResponse[RoleDefinitionsData]
