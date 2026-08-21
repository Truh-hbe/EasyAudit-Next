from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str = "postgresql+psycopg://easyaudit:easyaudit@localhost:5432/easyaudit"
    session_cookie_name: Literal["__Host-easyaudit_session"] = "__Host-easyaudit_session"
    session_ttl_seconds: int = Field(default=43_200, ge=300, le=2_592_000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
