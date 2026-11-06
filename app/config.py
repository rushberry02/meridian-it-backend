from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    support_api_key: SecretStr = SecretStr("")
    admin_api_key: SecretStr = SecretStr("")
    backend_url: str = "http://127.0.0.1:8000"

    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "meridian_it"
    db_user: str = "meridian_app"
    db_password: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()
