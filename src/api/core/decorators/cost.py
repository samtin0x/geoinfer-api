"""Cost management decorators for API endpoints."""

from functools import wraps

from fastapi import status

from src.database.models import ModelType
from src.modules.billing.credits import CreditConsumptionService
from src.utils.logger import get_logger
from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode

logger = get_logger(__name__)


def cost(
    credits: int | None = None,
    model_type: ModelType | None = None,
    model_id_param: str = "model_id",
):
    """
    Decorator to automatically handle credit consumption for API endpoints.

    Supports two modes:
    1. Static credits: Pass explicit `credits` and `model_type` values
    2. Dynamic (model-based): Automatically looks up `model_id` from request params
       and determines credits/model_type based on model type

    Args:
        credits: Static credit amount (optional - if None, uses model_id lookup)
        model_type: Static model type (optional - if None, uses model_id lookup)
        model_id_param: Name of the parameter containing ModelId (default: "model_id")

    Usage:
        # Dynamic - automatically gets cost from model_id parameter
        @cost()
        async def predict(model_id: ModelId = Query(...)):
            ...

        # Static - explicit credit amount
        @cost(credits=5, model_type=ModelType.GLOBAL)
        async def other_endpoint():
            ...

    The decorator will:
    1. Extract model_id from kwargs (if dynamic mode)
    2. Look up credit cost based on model type
    3. Execute the endpoint function
    4. Only consume credits if no exception was raised
    5. Store credits_to_consume and model_type in request.state for endpoint access
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            from src.api.core.decorators._common import extract_request_and_redis

            request, _ = extract_request_and_redis(*args, **kwargs)
            db = None

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

            # Extract auth info from request.state
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

            # Determine credits and model_type
            effective_credits = credits
            effective_model_type = model_type
            effective_model_id: str | None = None

            # If not static, look up from model_id parameter
            if effective_credits is None or effective_model_type is None:
                from src.modules.prediction.models import (
                    ModelId,
                    get_credit_cost,
                    get_model_type,
                )

                model_id_value: ModelId | None = kwargs.get(model_id_param)

                if model_id_value is None:
                    raise GeoInferException(
                        MessageCode.BAD_REQUEST,
                        status.HTTP_400_BAD_REQUEST,
                        details={
                            "description": f"Missing required parameter: {model_id_param}"
                        },
                    )

                effective_model_id = model_id_value.value
                if effective_credits is None:
                    effective_credits = get_credit_cost(model_id_value)
                if effective_model_type is None:
                    effective_model_type = get_model_type(model_id_value)

            # Store in request state so endpoint can access it
            request.state.credits_to_consume = effective_credits
            request.state.model_type = effective_model_type
            request.state.model_id = effective_model_id

            api_key_id = current_api_key.id if current_api_key else None

            # Execute the original function
            try:
                result = await func(*args, **kwargs)

                # Only consume credits if the function executed successfully
                credit_service = CreditConsumptionService(db)
                success, reason = await credit_service.consume_credits(
                    organization_id=current_organization.id,
                    credits_needed=effective_credits,
                    user_id=current_user.id if auth_type == "user" else None,
                    api_key_id=api_key_id,
                    model_type=effective_model_type,
                    model_id=effective_model_id,
                )

                if not success:
                    user_identifier = current_user.id if current_user else "API key"
                    logger.error(
                        f"Failed to consume credits for {user_identifier}: {reason}"
                    )
                    raise GeoInferException(
                        MessageCode.INSUFFICIENT_CREDITS,
                        status.HTTP_402_PAYMENT_REQUIRED,
                        details={
                            "description": reason,
                            "credits_required": effective_credits,
                        },
                    )

                logger.info(
                    f"Successfully consumed {effective_credits} credits for {auth_type} auth "
                    f"(model_type: {effective_model_type}, model_id: {effective_model_id})"
                )
                return result

            except Exception as e:
                logger.info(f"Request failed, credits not consumed: {str(e)}")
                raise

        return wrapper

    return decorator
