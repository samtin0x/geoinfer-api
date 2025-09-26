from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DEBUG: bool = False
    ENVIRONMENT: str = "DEV"
    API_VERSION: str = "0.0.1"
    CORS_ORIGINS: list[str] = [
        "http://localhost:3050",
        "http://localhost:3000",
        "https://geoinfer.com",
        "https://www.geoinfer.com",
        "https://app.geoinfer.com",
    ]

    # Admin portal settings
    ADMIN_EMAILS: list[str] = ["saul@geoinfer.com", "admin@geoinfer.com"]

    # Security settings
    MAX_REQUEST_SIZE: int = 10 * 1024 * 1024  # 10MB
    MAX_RESPONSE_SIZE: int = 10 * 1024 * 1024  # 10MB

    def validate_prod(self) -> None:
        """Sanity checks for production environment."""
        if self.ENVIRONMENT.upper() == "PROD":
            # Add minimal required checks; secrets checked in their own settings
            if not self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS must be set in production")
