"""User domain router for user-specific endpoints."""

from uuid import UUID
from fastapi import APIRouter, Request

from src.api.core.dependencies import (
    AsyncSessionDep,
    CurrentUserAuthDep,
    UserOnboardingServiceDep,
    OrganizationServiceDep,
)
from src.api.core.messages import APIResponse, MessageCode
from .handler import get_user_profile_handler, update_user_profile_handler
from .models import UserOrganizationModel
from .requests import (
    UserOrganizationsResponse,
    UserProfileResponse,
    UserProfileUpdateRequest,
)

router = APIRouter(prefix="/user", tags=["user"])


@router.get("/profile", response_model=UserProfileResponse)
async def get_current_user(
    request: Request,
    current_user: CurrentUserAuthDep,
) -> UserProfileResponse:
    """Get current user's profile information."""
    return await get_user_profile_handler(
        current_user=current_user,
    )


@router.patch("/profile", response_model=UserProfileResponse)
async def update_user_profile(
    request: Request,
    profile_data: UserProfileUpdateRequest,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> UserProfileResponse:
    """Update user profile information."""
    return await update_user_profile_handler(
        db=db,
        current_user=current_user,
        profile_data=profile_data,
    )


@router.get("/organizations", response_model=UserOrganizationsResponse)
async def list_user_organizations(
    request: Request,
    current_user: CurrentUserAuthDep,
    onboarding_service: UserOnboardingServiceDep,
) -> APIResponse[list[UserOrganizationModel]]:
    """List all organizations owned by the current user."""
    organizations = await onboarding_service.get_user_organizations(
        user_id=current_user.user.id,
    )

    # Convert organizations to response format using model validation
    org_data = []
    for org in organizations:
        org_dict = {
            "id": org.id,
            "name": org.name,
            "logo_url": org.logo_url,
            "created_at": org.created_at.isoformat(),
        }
        org_data.append(UserOrganizationModel.model_validate(org_dict))

    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data=org_data,
    )


@router.patch(
    "/organizations/{organization_id}/active", response_model=UserOrganizationsResponse
)
async def set_active_organization(
    organization_id: UUID,
    request: Request,
    current_user: CurrentUserAuthDep,
    org_service: OrganizationServiceDep,
    onboarding_service: UserOnboardingServiceDep,
) -> APIResponse[list[UserOrganizationModel]]:
    """Set a specific organization as active for the current user."""

    # Set the organization as active
    updated_org = await org_service.set_active_organization(
        user_id=current_user.user.id,
        organization_id=organization_id,
    )

    if not updated_org:
        from src.api.core.exceptions.base import GeoInferException
        from fastapi import status

        raise GeoInferException(
            MessageCode.ORGANIZATION_NOT_FOUND,
            status.HTTP_404_NOT_FOUND,
            {
                "description": f"Organization {organization_id} not found or not owned by user"
            },
        )

    # Return updated organizations list
    organizations = await onboarding_service.get_user_organizations(
        user_id=current_user.user.id,
    )

    org_data = []
    for org in organizations:
        org_dict = {
            "id": org.id,
            "name": org.name,
            "logo_url": org.logo_url,
            "created_at": org.created_at.isoformat(),
        }
        org_data.append(UserOrganizationModel.model_validate(org_dict))

    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data=org_data,
    )
