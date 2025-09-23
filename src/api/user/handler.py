"""User domain handlers."""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.core.messages import APIResponse, MessageCode
from src.services.auth.context import AuthenticatedUserContext
from .requests import UserProfileUpdateRequest, UserProfileResponse


async def get_user_profile_handler(
    current_user: AuthenticatedUserContext,
) -> UserProfileResponse:
    """Get user profile information."""

    return APIResponse.success(
        message_code=MessageCode.SUCCESS,
        data=current_user.user,
    )


async def update_user_profile_handler(
    db: AsyncSession,
    current_user: AuthenticatedUserContext,
    profile_data: UserProfileUpdateRequest,
) -> UserProfileResponse:
    """Update user profile information."""
    user = current_user.user

    # Update user fields
    if profile_data.name is not None:
        user.name = profile_data.name

    user.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(user)

    return APIResponse.success(
        message_code=MessageCode.USER_UPDATED,
        message="Profile updated successfully",
        data=user,
    )
