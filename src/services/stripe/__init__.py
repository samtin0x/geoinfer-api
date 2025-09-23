"""Stripe service module."""

from .service import StripePaymentService
from .constants import STRIPE_PRICE_MAP, CREDIT_PACKAGES, StripeProductType

# Alias for backwards compatibility
StripeService = StripePaymentService

__all__ = [
    "StripePaymentService",
    "StripeService",  # Alias for backwards compatibility
    "STRIPE_PRICE_MAP",
    "CREDIT_PACKAGES",
    "StripeProductType",
]
