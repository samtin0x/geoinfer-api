from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr


class R2Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    R2_ENDPOINT: str = ""
    R2_ACCESS_KEY: str = ""
    R2_SECRET_KEY: SecretStr = SecretStr("")
    R2_BUCKET: str = "geoinfer-geotagged"
