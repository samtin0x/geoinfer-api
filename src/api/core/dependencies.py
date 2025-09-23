from typing import Annotated, AsyncGenerator

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.services.auth.context import AuthenticatedUserContext
from src.services.auth.api_keys import ApiKeyManagementService
from src.services.auth.rate_limiting import RateLimiter
from src.services.organization.permissions import PermissionService
from src.services.organization.service import OrganizationService
from src.services.prediction.credits import PredictionCreditService
from src.services.redis_service import get_redis_client
from src.services.user.user_management import UserManagementService
from src.services.organization.invitation_manager import OrganizationInvitationService
from src.services.user_onboarding_service import UserOnboardingService
from src.services.user_organization_service import UserOrganizationService
from src.analytics.service import AnalyticsService


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Get database session from app state."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_user_management_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserManagementService:
    """Get user management service with database session."""
    return UserManagementService(db)


async def get_organization_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationService:
    """Get organization service with database session."""
    return OrganizationService(db)


async def get_permission_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> PermissionService:
    """Get permission service with database session."""
    return PermissionService(db)


async def get_api_key_management_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiKeyManagementService:
    """Get API key management service with database session."""
    return ApiKeyManagementService(db)


async def get_prediction_credit_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> PredictionCreditService:
    """Get prediction credit service with database session."""
    return PredictionCreditService(db)


async def get_organization_invitation_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationInvitationService:
    """Get organization invitation service with database session."""
    return OrganizationInvitationService(db)


async def get_user_onboarding_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserOnboardingService:
    """Get user onboarding service with database session."""
    return UserOnboardingService(db)


async def get_rate_limit_service(
    redis_client: redis.Redis = Depends(get_redis_client),
) -> RateLimiter:
    """Get rate limit service."""
    return RateLimiter(redis_client)


async def get_analytics_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AnalyticsService:
    """Get analytics service with database session."""
    return AnalyticsService(db)


async def get_user_organization_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserOrganizationService:
    """Get user organization service with database session."""
    return UserOrganizationService(db)


async def get_current_user_authenticated(request: Request) -> AuthenticatedUserContext:
    """Dependency to get current authenticated user with full context.

    Assumes auth middleware has properly set request.state.user, request.state.organization, and request.state.api_key.
    """
    # Auth middleware should have set these - if not, something is wrong with the middleware
    user = request.state.user
    organization = request.state.organization
    api_key = request.state.api_key

    if not user or not organization:
        raise GeoInferException(MessageCode.AUTH_REQUIRED, status.HTTP_401_UNAUTHORIZED)

    return AuthenticatedUserContext(
        user=user,
        organization=organization,
        api_key=api_key,
    )


AsyncSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
UserManagementServiceDep = Annotated[
    UserManagementService, Depends(get_user_management_service)
]
OrganizationServiceDep = Annotated[
    OrganizationService, Depends(get_organization_service)
]
PermissionServiceDep = Annotated[PermissionService, Depends(get_permission_service)]
ApiKeyManagementServiceDep = Annotated[
    ApiKeyManagementService, Depends(get_api_key_management_service)
]
PredictionCreditServiceDep = Annotated[
    PredictionCreditService, Depends(get_prediction_credit_service)
]
OrganizationInvitationServiceDep = Annotated[
    OrganizationInvitationService, Depends(get_organization_invitation_service)
]
UserOnboardingServiceDep = Annotated[
    UserOnboardingService, Depends(get_user_onboarding_service)
]
UserOrganizationServiceDep = Annotated[
    UserOrganizationService, Depends(get_user_organization_service)
]
RateLimitServiceDep = Annotated[RateLimiter, Depends(get_rate_limit_service)]
AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]

CurrentUserAuthDep = Annotated[
    AuthenticatedUserContext, Depends(get_current_user_authenticated)
]
