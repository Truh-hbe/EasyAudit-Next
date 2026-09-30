from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "postgresql+psycopg://easyaudit:easyaudit@localhost:5432/easyaudit"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str = DEFAULT_DATABASE_URL
    session_cookie_name: Literal["__Host-easyaudit_session"] = "__Host-easyaudit_session"
    session_ttl_seconds: int = Field(default=43_200, ge=300, le=2_592_000)
    session_touch_interval_seconds: int = Field(default=300, ge=0, le=3600)
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=5, ge=0, le=100)
    db_pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    db_pool_recycle_seconds: int = Field(default=1800, ge=-1)
    db_statement_timeout_ms: int = Field(default=15_000, ge=1)
    db_lock_timeout_ms: int = Field(default=5_000, ge=1)
    db_idle_in_transaction_timeout_ms: int = Field(default=30_000, ge=1)
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
