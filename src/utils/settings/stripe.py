"""Stripe settings configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

from src.utils.logger import get_logger

logger = get_logger(__name__)


class StripeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    STRIPE_WEBHOOK_SECRET: str = "whsec_test_webhook_secret"
    STRIPE_SECRET_KEY: SecretStr = SecretStr("sk_test_stripe_secret_key")

    STRIPE_PRICE_PRO_MONTHLY_EUR: str = "price_1SDBAmRrZbaFh87D6FHjgmUD"
    STRIPE_PRICE_PRO_YEARLY_EUR: str = "price_1SD3qKRrZbaFh87DFFqtFoIy"
    STRIPE_PRICE_PRO_OVERAGE_EUR: str = "price_1SDBBWRrZbaFh87DKE07lDxK"
    STRIPE_PRICE_TOPUP_STARTER_EUR: str = "price_1SDD4MRrZbaFh87D3FWQuZIP"
    STRIPE_PRICE_TOPUP_GROWTH_EUR: str = "price_1SD3tNRrZbaFh87DyH7XkX0m"
    STRIPE_PRICE_TOPUP_PRO_EUR: str = "price_1SD3ttRrZbaFh87DkUUaF367"

    STRIPE_METER_EVENT_NAME: str = "credit_overage"
    STRIPE_PORTAL_CONFIGURATION_ID: str = "bpc_1SDO8JRrZbaFh87DirgPzfTQ"
