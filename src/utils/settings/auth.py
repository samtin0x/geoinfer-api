from pydantic_settings import BaseSettings, SettingsConfigDict

from src.utils.logger import get_logger

logger = get_logger(__name__)


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    # Use plain string here to keep backward-compat with tests that treat this as a str
    SUPABASE_JWT_SECRET: str = ""
