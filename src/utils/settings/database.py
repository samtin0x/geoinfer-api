"""Database settings configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql://user:password@localhost:5433/geoinfer"

    @property
    def DATABASE_URL_ASYNC(self) -> str:
        """Derive async database URL from sync URL."""
        # Convert postgresql:// to postgresql+asyncpg://
        if self.DATABASE_URL.startswith("postgresql://"):
            return self.DATABASE_URL.replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )
        return self.DATABASE_URL
