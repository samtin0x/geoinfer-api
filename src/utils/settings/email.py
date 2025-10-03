"""Email settings configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.utils.logger import get_logger

logger = get_logger(__name__)


class EmailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    RESEND_API_KEY: str = ""
    EMAIL_FROM_DOMAIN: str = "mail.geoinfer.com"
    EMAIL_FROM_NAME: str = "GeoInfer"
    EMAIL_FROM_ADDRESS: str = "info"
