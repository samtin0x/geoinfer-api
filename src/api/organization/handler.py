"""Organization domain handlers."""

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import status

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import APIResponse, MessageCode
from src.cache.decorator import invalidate_organization_cache
from src.database.models import OrganizationPermission
from src.services.organization import OrganizationService, PermissionService
from src.utils.logger import get_logger
from .models import OrganizationModel
from .requests import (
    OrganizationCreateRequest,
    OrganizationCreateResponse,
    OrganizationUpdateRequest,
    OrganizationUpdateResponse,
    RemoveUserResponse,
)

logger = get_logger(__name__)


async def create_organization_handler(
    db: AsyncSession,
    organization_data: OrganizationCreateRequest,
    user_id: UUID,
) -> OrganizationCreateResponse:
    """Create a new organization (enterprise only)."""
    org_service = OrganizationService(db)

    organization = await org_service.create_organization(
        name=organization_data.name,
        user_id=user_id,  # Business orgs belong to the user who created them
        logo_url=(
            str(organization_data.logo_url) if organization_data.logo_url else None
        ),
    )

    logger.info(f"Created organization {organization.id} for user {user_id}")

    return APIResponse.success(
        message_code=MessageCode.ORGANIZATION_CREATED,
        data=OrganizationModel(
            id=organization.id,
            name=organization.name,
            logo_url=organization.logo_url,
            created_at=organization.created_at,
        ),
    )


async def update_organization_handler(
    db: AsyncSession,
    organization_id: UUID,
    organization_data: OrganizationUpdateRequest,
    requesting_user_id: UUID,
) -> OrganizationUpdateResponse:
    """Update organization details with permission check."""
    permission_service = PermissionService(db)

    # Check if user has permission to manage organization
    has_permission = await permission_service.check_user_permission(
        user_id=requesting_user_id,
        organization_id=organization_id,
        permission=OrganizationPermission.MANAGE_ORGANIZATION,
    )

    if not has_permission:
        raise GeoInferException(
            MessageCode.INSUFFICIENT_PERMISSIONS,
            status.HTTP_403_FORBIDDEN,
            {"description": "Insufficient permissions to update organization"},
        )

    org_service = OrganizationService(db)
    organization = await org_service.update_organization_details(
        organization_id=organization_id,
        new_name=organization_data.name,
        new_logo_url=(
            str(organization_data.logo_url) if organization_data.logo_url else None
        ),
        requesting_user_id=requesting_user_id,
    )

    if not organization:
        raise GeoInferException(
            MessageCode.ORGANIZATION_NOT_FOUND,
            status.HTTP_404_NOT_FOUND,
            {"description": "Organization not found"},
        )

    # Invalidate organization cache for all members
    await invalidate_organization_cache(organization_id)

    logger.info(f"Updated organization {organization_id} and invalidated cache")

    return APIResponse.success(
        message_code=MessageCode.ORGANIZATION_UPDATED,
        data=OrganizationModel(
            id=organization.id,
            name=organization.name,
            logo_url=organization.logo_url,
            created_at=organization.created_at,
        ),
    )


async def remove_user_from_organization_handler(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    requesting_user_id: UUID,
) -> RemoveUserResponse:
    """Remove a user from an organization (enterprise only, manage members permission required)."""
    permission_service = PermissionService(db)

    # Check if requesting user has permission to manage members
    has_permission = await permission_service.check_user_permission(
        user_id=requesting_user_id,
        organization_id=organization_id,
        permission=OrganizationPermission.MANAGE_MEMBERS,
    )

    if not has_permission:
        raise GeoInferException(
            MessageCode.INSUFFICIENT_PERMISSIONS,
            status.HTTP_403_FORBIDDEN,
            {"description": "Insufficient permissions to manage members"},
        )

    # Prevent users from removing themselves
    if user_id == requesting_user_id:
        raise GeoInferException(
            MessageCode.CANNOT_REMOVE_YOURSELF,
            status.HTTP_400_BAD_REQUEST,
            {"description": "Cannot remove yourself from organization"},
        )

    success = await permission_service.remove_user_from_organization(
        user_id=user_id,
        organization_id=organization_id,
        requesting_user_id=requesting_user_id,
    )

    if not success:
        raise GeoInferException(
            MessageCode.USER_NOT_MEMBER_OF_ORGANIZATION,
            status.HTTP_400_BAD_REQUEST,
            {"description": "User is not a member of this organization"},
        )

    # Invalidate organization cache for all members
    await invalidate_organization_cache(organization_id)

    logger.info(f"User {user_id} removed from organization {organization_id}")

    return APIResponse.success(
        message_code=MessageCode.USER_REMOVED_FROM_ORGANIZATION,
        message=f"User {user_id} removed from organization {organization_id}",
        data={"removed_user_id": str(user_id), "organization_id": str(organization_id)},
    )
