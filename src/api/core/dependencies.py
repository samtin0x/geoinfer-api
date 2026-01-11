from typing import Annotated, AsyncGenerator

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.core.context import AuthenticatedUserContext
from src.modules.keys.api_keys import ApiKeyManagementService
from src.core.rate_limiting import RateLimiter
from src.modules.organization.permissions import PermissionService
from src.modules.organization.use_cases import OrganizationService
from src.modules.billing.credits import CreditConsumptionService
from src.redis.client import get_redis_client
from src.modules.user.management import UserManagementService
from src.modules.organization.invitation import (
    OrganizationInvitationService,
)
from src.modules.user.onboarding import UserOnboardingService
from src.modules.user.organization import UserOrganizationService
from src.modules.analytics.service import AnalyticsService
from src.modules.prediction.infrastructure.gpu_client import (
    GPUServerClient,
    get_gpu_client,
)
from src.utils.r2_client import R2Client
from src.utils.settings.app import AppSettings

_is_production = AppSettings().ENVIRONMENT.upper() == "PROD"


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
) -> CreditConsumptionService:
    """Get prediction credit service with database session."""
    return CreditConsumptionService(db)


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


async def get_gpu_server_client() -> GPUServerClient:
    """Get GPU server client."""
    return await get_gpu_client()


def get_r2_client() -> R2Client:
    """Get R2 client. Uploads disabled in non-production environments."""
    return R2Client(upload_predictions=_is_production)


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
    CreditConsumptionService, Depends(get_prediction_credit_service)
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
GPUServerClientDep = Annotated[GPUServerClient, Depends(get_gpu_server_client)]
R2ClientDep = Annotated[R2Client, Depends(get_r2_client)]

CurrentUserAuthDep = Annotated[
    AuthenticatedUserContext, Depends(get_current_user_authenticated)
]
