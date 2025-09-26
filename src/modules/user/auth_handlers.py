"""Authentication handlers for JWT and API key authentication."""

import redis.asyncio as redis
from fastapi import Request, status
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.core.constants import (
    GEO_API_KEY_PREFIX,
    JWT_ALGORITHM,
)
from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.core.context import AuthenticatedUserContext
from src.cache import cached
from src.modules.keys.api_keys import ApiKeyManagementService
from src.modules.user.management import UserManagementService
from src.utils.settings.auth import AuthSettings
from src.utils.logger import get_logger

logger = get_logger(__name__)


@cached(3600)
async def handle_jwt_auth(
    request: Request,
    db: AsyncSession,
    redis_client: redis.Redis,
    token: str,
) -> AuthenticatedUserContext:
    try:
        payload = jwt.decode(
            token,
            AuthSettings().SUPABASE_JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            audience="authenticated",
        )
    except JWTError as e:
        logger.error(f"JWT decoding failed: {e}")
        raise GeoInferException(
            MessageCode.INVALID_TOKEN,
            status.HTTP_403_FORBIDDEN,
            {"description": "Invalid or expired authentication token"},
        )

    if payload.get("role") == "anon":
        raise GeoInferException(
            MessageCode.INSUFFICIENT_PERMISSIONS,
            status.HTTP_403_FORBIDDEN,
            {"description": "Anonymous access not permitted"},
        )

    auth_service = UserManagementService(db)
    user, organization = await auth_service.handle_jwt_authentication(payload=payload)

    return AuthenticatedUserContext(user=user, organization=organization, api_key=None)


@cached(300)
async def handle_api_key_auth(
    request: Request,
    db: AsyncSession,
    redis_client: redis.Redis,
    api_key: str,
) -> AuthenticatedUserContext:
    if not api_key.startswith(GEO_API_KEY_PREFIX):
        raise GeoInferException(
            MessageCode.INVALID_API_KEY,
            status.HTTP_401_UNAUTHORIZED,
            {"description": f"API key must start with '{GEO_API_KEY_PREFIX}'"},
        )

    api_key_service = ApiKeyManagementService(db)
    result = await api_key_service.verify_api_key(api_key)
    if not result:
        raise GeoInferException(
            MessageCode.INVALID_API_KEY,
            status.HTTP_401_UNAUTHORIZED,
            {"description": "API key is invalid or expired"},
        )

    api_key_obj, user = result
    user_management = UserManagementService(db)
    organization = await user_management.get_user_organization(user.id)
    if not organization:
        raise GeoInferException(
            MessageCode.INVALID_API_KEY,
            status.HTTP_401_UNAUTHORIZED,
            {"description": "User organization not found"},
        )

    return AuthenticatedUserContext(
        user=user, organization=organization, api_key=api_key_obj
    )
