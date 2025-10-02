"""Cost management decorators for API endpoints."""

from functools import wraps

from fastapi import status

from src.database.models import UsageType
from src.modules.billing.credits import CreditConsumptionService
from src.utils.logger import get_logger
from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode

logger = get_logger(__name__)


def cost(credits: int = 1, usage_type: UsageType = UsageType.GEOINFER_GLOBAL_0_0_1):
    """
    Decorator to automatically handle credit consumption for API endpoints.

    Features:
    - Only consumes credits if the request succeeds
    - Works with both user auth and API key auth
    - Supports overage (if enabled) when subscription/top-up credits are exhausted

    Args:
        credits: Number of credits to consume (defaults to GLOBAL_MODEL_CREDIT_COST)
        usage_type: Type of usage (defaults to GEOINFER_GLOBAL_0_0_1)

    Usage:
        @cost()  # Uses GLOBAL_MODEL_CREDIT_COST (default: 1)
        @cost(credits=5)  # Use specific credit amount
        @with_user_auth()
        async def my_endpoint(request: Request, current_user: dict = None):
            # Your endpoint logic here
            return {"result": "success"}

    The decorator will:
    1. Extract user/api_key info from the decorated endpoint
    2. Execute the endpoint function
    3. Only consume credits if no exception was raised
    4. Credits consumed in order: subscription → top-ups → overage (if enabled)
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Use shared extractor for Request
            from src.api.core.decorators._common import extract_request_and_redis

            request, _ = extract_request_and_redis(*args, **kwargs)
            db = None
            current_user = None
            current_api_key = None
            auth_type = None

            # Find DB session
            for arg in args:
                if hasattr(arg, "execute"):
                    db = arg
                    break

            if not db:
                for value in kwargs.values():
                    if hasattr(value, "execute"):
                        db = value
                        break

            # Extract auth info from request.state (set by auth middleware)
            current_user = request.state.user if request else None
            current_organization = request.state.organization if request else None
            current_api_key = request.state.api_key if request else None
            auth_type = "api_key" if current_api_key else "user"

            if not request or not db:
                raise GeoInferException(
                    MessageCode.INTERNAL_SERVER_ERROR,
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    details={
                        "description": "Cost decorator requires Request and AsyncSession"
                    },
                )

            if not current_user and not current_api_key:
                raise GeoInferException(
                    MessageCode.AUTH_REQUIRED,
                    status.HTTP_401_UNAUTHORIZED,
                )

            api_key_id = None
            if auth_type == "api_key" and current_api_key:
                api_key_id = current_api_key.id

            # Execute the original function
            try:
                result = await func(*args, **kwargs)

                # Only consume credits if the function executed successfully
                if not current_user and not current_api_key:
                    raise GeoInferException(
                        MessageCode.INTERNAL_SERVER_ERROR,
                        status.HTTP_500_INTERNAL_SERVER_ERROR,
                        details={
                            "description": "Authentication failed - no user or API key found"
                        },
                    )

                credit_service = CreditConsumptionService(db)
                success, reason = await credit_service.consume_credits(
                    organization_id=current_organization.id,
                    credits_needed=credits,
                    user_id=current_user.id if auth_type == "user" else None,
                    api_key_id=api_key_id,
                )

                if not success:
                    user_identifier = current_user.id if current_user else "API key"
                    logger.error(
                        f"Failed to consume credits for {user_identifier}: {reason}"
                    )
                    raise GeoInferException(
                        MessageCode.INSUFFICIENT_CREDITS,
                        status.HTTP_402_PAYMENT_REQUIRED,
                        details={"description": reason},
                    )

                logger.info(
                    f"Successfully consumed {credits} credits for {auth_type} auth"
                )
                return result

            except Exception as e:
                # If the function failed, don't consume credits
                logger.info(f"Request failed, credits not consumed: {str(e)}")
                raise

        return wrapper

    return decorator
