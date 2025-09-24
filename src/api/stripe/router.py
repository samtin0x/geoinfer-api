"""Stripe webhook endpoints."""

from fastapi import APIRouter, Request, status

from src.api.core.dependencies import AsyncSessionDep
from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.modules.billing.use_cases import StripePaymentService
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/stripe", tags=["stripe"])


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: AsyncSessionDep,
):
    """Handle Stripe webhook events."""
    try:
        # Get raw payload and signature
        payload = await request.body()
        signature = request.headers.get("stripe-signature")

        if not signature:
            raise GeoInferException(
                MessageCode.BAD_REQUEST,
                status.HTTP_400_BAD_REQUEST,
                details={"description": "Missing stripe-signature header"},
            )

        # Initialize Stripe service
        stripe_service = StripePaymentService(db)

        # Validate webhook signature and get event
        event = stripe_service.validate_webhook_signature(payload, signature)

        # Handle the event
        success = await stripe_service.handle_subscription_webhook(event)

        if success:
            logger.info(f"Successfully processed webhook event: {event['type']}")
            return {"status": "success"}
        else:
            logger.warning(f"Webhook event not handled: {event['type']}")
            return {"status": "ignored"}

    except ValueError as e:
        logger.error(f"Webhook validation error: {e}")
        raise GeoInferException(
            MessageCode.BAD_REQUEST,
            status.HTTP_400_BAD_REQUEST,
            details={"description": str(e)},
        )
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        raise GeoInferException(
            MessageCode.INTERNAL_ERROR, status.HTTP_500_INTERNAL_SERVER_ERROR
        )
