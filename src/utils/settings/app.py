from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DEBUG: bool = False
    ENVIRONMENT: str = "DEV"
    CORS_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:3002",
        "https://geoinfer.com",
        "https://app.geoinfer.com",
    ]

    # Admin portal settings
    ADMIN_EMAILS: list = ["saul@geoinfer.com", "admin@geoinfer.com"]

    # Security settings
    MAX_REQUEST_SIZE: int = 10 * 1024 * 1024  # 10MB
    MAX_RESPONSE_SIZE: int = 10 * 1024 * 1024  # 10MB
    MAX_IMAGE_SIZE: int = 5 * 1024 * 1024  # 5MB for image uploads
