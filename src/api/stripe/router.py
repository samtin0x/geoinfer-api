"""Stripe webhook endpoint."""

from fastapi import APIRouter, Request, status
import time

from src.api.core.dependencies import AsyncSessionDep
from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.modules.billing.stripe.service import StripePaymentService
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/stripe", tags=["stripe"])


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: AsyncSessionDep,
):
    """Handle Stripe webhook events with enhanced security verification."""
    try:
        # Get raw payload and signature with security checks
        payload = await request.body()

        # Security: Ensure payload is not empty and reasonable size
        if not payload:
            raise GeoInferException(
                MessageCode.BAD_REQUEST,
                status.HTTP_400_BAD_REQUEST,
                details={"description": "Empty webhook payload"},
            )

        if len(payload) > 1024 * 1024:  # 1MB limit
            raise GeoInferException(
                MessageCode.BAD_REQUEST,
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                details={"description": "Webhook payload too large"},
            )

        signature = request.headers.get("stripe-signature")

        if not signature:
            raise GeoInferException(
                MessageCode.BAD_REQUEST,
                status.HTTP_400_BAD_REQUEST,
                details={"description": "Missing stripe-signature header"},
            )

        # Security: Validate signature format (should contain timestamp and signatures)
        if not signature.startswith("t=") or ",v" not in signature:
            raise GeoInferException(
                MessageCode.BAD_REQUEST,
                status.HTTP_400_BAD_REQUEST,
                details={"description": "Invalid stripe-signature format"},
            )

        # Initialize Stripe service
        stripe_service = StripePaymentService(db)

        # Validate webhook signature and get event (includes timestamp tolerance check)
        event = stripe_service.validate_webhook_signature(payload, signature)

        # Security: Check event timestamp is recent (within 5 minutes)
        event_timestamp = event.get("created", 0)
        current_time = int(time.time())

        if abs(current_time - event_timestamp) > 300:  # 5 minutes tolerance
            logger.warning(f"Webhook event timestamp too old: {event_timestamp}")
            raise GeoInferException(
                MessageCode.BAD_REQUEST,
                status.HTTP_400_BAD_REQUEST,
                details={"description": "Webhook event timestamp too old"},
            )

        # Handle the event
        success = await stripe_service.handle_webhook_event(event)

        if success:
            logger.info(f"Successfully processed webhook event: {event['type']}")
            return {"status": "success"}
        else:
            logger.debug(f"Webhook event not handled: {event['type']}")
            return {"status": "ignored"}

    except ValueError as e:
        logger.error(f"Webhook validation error: {e}")
        raise GeoInferException(
            MessageCode.BAD_REQUEST,
            status.HTTP_400_BAD_REQUEST,
            details={"description": "Invalid webhook data"},
        )
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        raise GeoInferException(
            MessageCode.INTERNAL_ERROR, status.HTTP_500_INTERNAL_SERVER_ERROR
        )
