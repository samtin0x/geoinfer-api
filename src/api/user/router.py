"""User domain router for user-specific endpoints."""

from fastapi import APIRouter, Request

from src.api.core.dependencies import (
    AsyncSessionDep,
    CurrentUserAuthDep,
    UserOnboardingServiceDep,
    OrganizationServiceDep,
)
from src.api.core.messages import APIResponse, MessageCode
from src.api.user.schemas import UserOrganizationModel
from src.api.user.schemas import (
    UserOrganizationsResponse,
    UserProfileResponse,
    UserProfileUpdateRequest,
    SetActiveOrganizationRequest,
    SetActiveOrganizationResponse,
)
from src.database.models.users import User as UserModel
from datetime import datetime, timezone


router = APIRouter(prefix="/user", tags=["user"])


@router.get("/profile", response_model=UserProfileResponse)
async def get_current_user(
    request: Request,
    current_user: CurrentUserAuthDep,
) -> UserProfileResponse:
    """Get current user's profile information."""
    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data=current_user.user,
    )


@router.patch("/profile", response_model=UserProfileResponse)
async def update_user_profile(
    request: Request,
    profile_data: UserProfileUpdateRequest,
    db: AsyncSessionDep,
    current_user: CurrentUserAuthDep,
) -> UserProfileResponse:
    """Update user profile information."""
    # Reload the user within the active session to ensure persistence
    user = await db.get(UserModel, current_user.user.id)  # type: ignore
    user.name = profile_data.name  # type: ignore

    user.updated_at = datetime.now(timezone.utc)  # type: ignore
    await db.commit()
    await db.refresh(user)

    return APIResponse.success(
        message_code=MessageCode.USER_UPDATED,
        message="Profile updated successfully",
        data=user,
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


@router.patch("/organizations/active", response_model=SetActiveOrganizationResponse)
async def set_active_organization(
    request_data: SetActiveOrganizationRequest,
    request: Request,
    current_user: CurrentUserAuthDep,
    org_service: OrganizationServiceDep,
) -> SetActiveOrganizationResponse:
    """Set a specific organization as active for the current user."""

    success = await org_service.set_active_organization(
        user_id=current_user.user.id,
        organization_id=request_data.organization_id,
    )

    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data=success,
    )
