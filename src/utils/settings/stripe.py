"""Stripe settings configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

from src.utils.logger import get_logger

logger = get_logger(__name__)


class StripeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    STRIPE_WEBHOOK_SECRET: str = "whsec_test_webhook_secret"
    STRIPE_SECRET_KEY: SecretStr = SecretStr("sk_test_stripe_secret_key")
