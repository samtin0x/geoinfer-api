from functools import wraps
from uuid import UUID

from fastapi import Request, status

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.utils.logger import get_logger

logger = get_logger(__name__)

ADMIN_USER_IDS = {
    UUID("d46e8d64-26a1-45a7-a9fa-0207a9a50aab"),
}


def admin():
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request in args/kwargs
            request = None

            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            for key, value in kwargs.items():
                if isinstance(value, Request):
                    request = value
                    break

            # Validate request exists
            if not request:
                raise GeoInferException(
                    MessageCode.AUTH_REQUIRED,
                    status.HTTP_401_UNAUTHORIZED,
                    {"description": "Request object not found"},
                )

            # Get user from request state (set by auth middleware)
            user = getattr(request.state, "user", None)

            if not user:
                raise GeoInferException(
                    MessageCode.AUTH_REQUIRED,
                    status.HTTP_401_UNAUTHORIZED,
                    {"description": "Authentication required"},
                )

            # Check if user is admin
            if user.id not in ADMIN_USER_IDS:
                logger.warning(
                    "Unauthorized admin access attempt",
                    user_id=str(user.id),
                    endpoint=request.url.path,
                )
                raise GeoInferException(
                    MessageCode.AUTH_FORBIDDEN,
                    status.HTTP_403_FORBIDDEN,
                    {"description": "Admin access required"},
                )

            logger.info(
                "Admin access granted",
                user_id=str(user.id),
                endpoint=request.url.path,
            )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
