"""Real Stripe webhook event fixtures for testing."""

from datetime import datetime, timezone

# Real invoice.paid event
INVOICE_PAID_EVENT = {
    "id": "evt_test_invoice_paid",
    "object": "event",
    "type": "invoice.paid",
    "data": {
        "object": {
            "id": "in_1SDCfJRrZbaFh87DqX5NDDsi",
            "object": "invoice",
            "account_country": "ES",
            "account_name": "GeoInfer sandbox",
            "account_tax_ids": None,
            "amount_due": 6000,
            "amount_overpaid": 0,
            "amount_paid": 6000,
            "amount_remaining": 0,
            "amount_shipping": 0,
            "billing_reason": "subscription_create",
            "collection_method": "charge_automatically",
            "created": 1759273741,
            "currency": "eur",
            "customer": "cus_T9VghcmQadyKMh",
            "customer_email": "test@test.test",
            "customer_name": "asaa dsads",
            "status": "paid",
            "subscription": "sub_1SDCfLRrZbaFh87DmGzQpcLQ",
            "period_start": 1759273741,
            "period_end": 1759273741,
            "lines": {
                "object": "list",
                "data": [
                    {
                        "id": "il_1SDCfJRrZbaFh87DVmHQOlHN",
                        "object": "line_item",
                        "amount": 6000,
                        "currency": "eur",
                        "description": "1 × PRO Subcription (at €60.00 / month)",
                        "period": {"end": 1761865741, "start": 1759273741},
                        "quantity": 1,
                    }
                ],
            },
        }
    },
}

# Real customer.subscription.created event
CUSTOMER_SUBSCRIPTION_CREATED_EVENT = {
    "id": "evt_test_subscription_created",
    "object": "event",
    "type": "customer.subscription.created",
    "data": {
        "object": {
            "id": "sub_1SDCfLRrZbaFh87DmGzQpcLQ",
            "object": "subscription",
            "billing_cycle_anchor": 1759273741,
            "billing_cycle_anchor_config": None,
            "billing_mode": {"flexible": None, "type": "classic"},
            "cancel_at_period_end": False,
            "created": 1759273741,
            "currency": "eur",
            "customer": "cus_T9VghcmQadyKMh",
            "status": "active",
            "items": {
                "object": "list",
                "data": [
                    {
                        "id": "si_T9VgiXO2dZ37UL",
                        "object": "subscription_item",
                        "created": 1759273741,
                        "current_period_end": 1761865741,
                        "current_period_start": 1759273741,
                        "plan": {
                            "id": "price_1SDBAmRrZbaFh87D6FHjgmUD",
                            "object": "plan",
                            "active": True,
                            "amount": 6000,
                            "currency": "eur",
                            "interval": "month",
                            "interval_count": 1,
                            "product": "prod_T9MZsEKfgPRFjO",
                            "usage_type": "licensed",
                        },
                        "price": {
                            "id": "price_1SDBAmRrZbaFh87D6FHjgmUD",
                            "object": "price",
                            "active": True,
                            "billing_scheme": "per_unit",
                            "currency": "eur",
                            "product": "prod_T9MZsEKfgPRFjO",
                            "recurring": {
                                "interval": "month",
                                "interval_count": 1,
                                "usage_type": "licensed",
                            },
                            "type": "recurring",
                            "unit_amount": 6000,
                        },
                        "quantity": 1,
                        "subscription": "sub_1SDCfLRrZbaFh87DmGzQpcLQ",
                    }
                ],
                "has_more": False,
                "total_count": 1,
            },
            "latest_invoice": "in_1SDCfJRrZbaFh87DqX5NDDsi",
        }
    },
}

# Real checkout.session.completed event
CHECKOUT_SESSION_COMPLETED_EVENT = {
    "id": "evt_test_checkout_completed",
    "object": "event",
    "type": "checkout.session.completed",
    "data": {
        "object": {
            "id": "cs_test_b19LC3pr3AjhFxQ5iRafWmk69B1WtmurGY4ncbuorF4FFSy6Uu7x8OizP8",
            "object": "checkout.session",
            "amount_subtotal": 6000,
            "amount_total": 6000,
            "cancel_url": "http://localhost:3050/en/billing?cancelled=true",
            "created": 1759273727,
            "currency": "eur",
            "customer": "cus_T9VghcmQadyKMh",
            "customer_creation": "always",
            "customer_details": {
                "address": {
                    "city": None,
                    "country": "ES",
                    "line1": None,
                    "line2": None,
                    "postal_code": None,
                    "state": None,
                },
                "email": "test@test.test",
                "name": "asaa dsads",
                "phone": None,
                "tax_exempt": "none",
                "tax_ids": [],
            },
            "customer_email": "test@test.test",
            "invoice": "in_1SDCfJRrZbaFh87DqX5NDDsi",
            "metadata": {
                "organization_id": "d46e8d64-26a1-45a7-a9fa-0207a9a50aab",
                "product_type": "subscription",
            },
            "mode": "subscription",
            "payment_status": "paid",
            "status": "complete",
            "subscription": "sub_1SDCfLRrZbaFh87DmGzQpcLQ",
            "success_url": "http://localhost:3050/en/billing?session_id={CHECKOUT_SESSION_ID}&success=subscription",
        }
    },
}


def get_subscription_data_with_items(
    subscription_id: str = "sub_test_123",
    customer_id: str = "cus_test_456",
    price_id: str = "price_1SDBAmRrZbaFh87D6FHjgmUD",
    status: str = "active",
    current_period_start: int | None = None,
    current_period_end: int | None = None,
) -> dict:
    """Helper to create subscription data with items (matches real Stripe structure)."""
    if current_period_start is None:
        current_period_start = int(datetime.now(timezone.utc).timestamp())
    if current_period_end is None:
        current_period_end = int(
            datetime.now(timezone.utc).timestamp() + 30 * 24 * 60 * 60
        )

    return {
        "id": subscription_id,
        "object": "subscription",
        "billing_cycle_anchor": current_period_start,
        "customer": customer_id,
        "status": status,
        "items": {
            "object": "list",
            "data": [
                {
                    "id": f"si_{subscription_id}_item",
                    "object": "subscription_item",
                    "current_period_start": current_period_start,
                    "current_period_end": current_period_end,
                    "price": {
                        "id": price_id,
                        "object": "price",
                        "recurring": {"usage_type": "licensed"},
                    },
                    "subscription": subscription_id,
                }
            ],
        },
    }
