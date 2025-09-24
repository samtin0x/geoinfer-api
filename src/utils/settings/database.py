"""Database settings configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

from src.utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: SecretStr = SecretStr(
        "postgresql://user:password@localhost:5433/geoinfer"
    )

    @property
    def DATABASE_URL_ASYNC(self) -> str:
        """Derive async database URL from sync URL."""
        # Convert postgresql:// to postgresql+asyncpg://
        url = self.DATABASE_URL.get_secret_value()
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url
