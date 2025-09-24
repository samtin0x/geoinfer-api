"""Authentication and permission decorators."""

from functools import wraps

from fastapi import Request

from src.api.core.exceptions.base import GeoInferException
from src.database.models import OrganizationPermission, PlanTier
from src.modules.organization.permissions import PermissionService
from src.utils.logger import get_logger
from src.api.core.messages import MessageCode
from fastapi import status

logger = get_logger(__name__)


def require_permission(permission: OrganizationPermission):
    """
    Decorator to check organization permissions.

    Args:
        permission: The organization permission to check

    Uses organization_id and user_id from request.state (set by auth middleware).
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request and db in args/kwargs
            request = None
            db = None

            # Check function arguments for request and db
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                elif hasattr(arg, "execute"):  # AsyncSession duck typing
                    db = arg

            # Check keyword arguments for request and db
            for key, value in kwargs.items():
                if isinstance(value, Request):
                    request = value
                elif hasattr(value, "execute"):  # AsyncSession duck typing
                    db = value

            # Validate required components
            if not request:
                raise GeoInferException(
                    MessageCode.AUTH_REQUIRED,
                    status.HTTP_401_UNAUTHORIZED,
                    {"description": "Request object not found"},
                )
            if not db:
                raise ValueError("Database session not found in function parameters")

            # Get user info and organization_id from already-validated request state
            user_id = request.state.user.id if request.state.user else None
            user_info = request.state.user
            organization_id = request.state.organization.id

            if not user_id or not user_info or not organization_id:
                raise GeoInferException(
                    MessageCode.AUTH_MISSING_CONTEXT,
                    status.HTTP_401_UNAUTHORIZED,
                    {
                        "description": "User authentication required for permission check"
                    },
                )

            # Check permission
            permission_service = PermissionService(db)
            has_permission = await permission_service.check_user_permission(
                user_id=user_id,
                organization_id=organization_id,
                permission=permission,
            )

            if not has_permission:
                raise GeoInferException(
                    MessageCode.AUTH_INSUFFICIENT_ROLE_PERMISSIONS,
                    status.HTTP_403_FORBIDDEN,
                    details={"permission": permission.value},
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_plan_tier(allowed_tiers: list[PlanTier]):
    """
    Decorator to check if the user's organization has one of the allowed plan tiers.

    Args:
        allowed_tiers: List of plan tiers that can access this endpoint

    Uses organization from request.state (set by auth middleware).
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request in args/kwargs
            request = None

            # Check function arguments for request
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            # Check keyword arguments for request
            if not request:
                for key, value in kwargs.items():
                    if isinstance(value, Request):
                        request = value
                        break

            # Validate required components
            if not request:
                raise GeoInferException(
                    MessageCode.AUTH_REQUIRED,
                    status.HTTP_401_UNAUTHORIZED,
                    {"description": "Request object not found"},
                )

            # Get organization from already-validated request state
            organization = getattr(request.state, "organization", None)

            if not organization:
                raise GeoInferException(
                    MessageCode.AUTH_MISSING_CONTEXT,
                    status.HTTP_403_FORBIDDEN,
                    {
                        "description": "Organization context required for plan tier check"
                    },
                )

            # Check if organization has one of the allowed plan tiers
            allowed_tier_values = [tier for tier in allowed_tiers]
            if organization.plan_tier not in allowed_tier_values:
                raise GeoInferException(
                    MessageCode.AUTH_INSUFFICIENT_PLAN_TIER,
                    status.HTTP_403_FORBIDDEN,
                    {
                        "description": f"This feature requires one of the following plan tiers: {', '.join(allowed_tier_values)}",
                        "current_tier": organization.plan_tier,
                        "allowed_tiers": allowed_tier_values,
                    },
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
