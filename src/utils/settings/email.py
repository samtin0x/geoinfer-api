"""Email settings configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.utils.logger import get_logger

logger = get_logger(__name__)


class EmailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    RESEND_API_KEY: str
    from_email_no_reply: str = "no-reply@geoinfer.com"
    from_name: str = "GeoInfer"
