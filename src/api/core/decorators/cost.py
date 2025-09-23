"""Cost management decorators for API endpoints."""

from functools import wraps

from fastapi import Request, status

from src.database.models import UsageType
from src.services.prediction.credits import PredictionCreditService
from src.utils.logger import get_logger
from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode

logger = get_logger(__name__)


def cost(credits: int = 1, usage_type: UsageType = UsageType.GEOINFER_GLOBAL_0_0_1):
    """
    Decorator to automatically handle credit consumption for API endpoints.

    Features:
    - Pre-checks if user has enough credits
    - Only consumes credits if the request succeeds
    - Works with both user auth and API key auth

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
    2. Check if sufficient credits are available
    3. Execute the endpoint function
    4. Only consume credits if no exception was raised
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract required objects from kwargs
            request = None
            db = None
            current_user = None
            current_api_key = None
            auth_type = None

            # Find request object
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            if not request:
                for value in kwargs.values():
                    if isinstance(value, Request):
                        request = value
                        break

            # Find database session
            for arg in args:
                if hasattr(arg, "execute"):  # AsyncSession duck typing
                    db = arg
                    break

            if not db:
                for value in kwargs.values():
                    if hasattr(value, "execute"):  # AsyncSession duck typing
                        db = value
                        break

            # Extract auth info from request.state (set by auth middleware)
            current_user = request.state.user
            current_organization = request.state.organization
            current_api_key = request.state.api_key
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

            # Initialize credit service
            credit_service = PredictionCreditService(db)

            # Check organization's credit balance - treat user and API key auth the same way
            subscription_credits, top_up_credits = (
                await credit_service.get_organization_credits(
                    organization_id=current_organization.id
                )
            )
            available_credits = subscription_credits + top_up_credits

            if available_credits < credits:
                raise GeoInferException(
                    MessageCode.INSUFFICIENT_CREDITS,
                    status.HTTP_402_PAYMENT_REQUIRED,
                    details={
                        "required_credits": credits,
                        "available_credits": available_credits,
                    },
                )

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

                success = await credit_service.consume_credits(
                    organization_id=current_organization.id,
                    credits_to_consume=credits,
                    user_id=current_user.id if auth_type == "user" else None,
                    api_key_id=api_key_id,
                    usage_type=usage_type,
                )

                if not success:
                    user_identifier = current_user.id if current_user else "API key"
                    logger.error(f"Failed to consume credits for {user_identifier}")
                    raise GeoInferException(
                        MessageCode.INSUFFICIENT_CREDITS,
                        status.HTTP_402_PAYMENT_REQUIRED,
                        details={
                            "description": "Failed to consume credits - please contact support"
                        },
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
