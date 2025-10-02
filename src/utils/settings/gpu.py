"""GPU Server settings configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class GPUServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    GPU_SERVER_URL: str = "http://136.59.129.136:33234"
    GPU_SERVER_USERNAME: str = "admin"
    GPU_SERVER_PASSWORD: str = "mypassword"
    GPU_SERVER_TIMEOUT: int = 60


gpu_settings = GPUServerSettings()
