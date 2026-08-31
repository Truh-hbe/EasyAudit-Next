from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str = "postgresql+psycopg://easyaudit:easyaudit@localhost:5432/easyaudit"
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_pool_timeout_seconds: int = Field(default=5, ge=1, le=30)
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    database_statement_timeout_ms: int = Field(default=15_000, ge=1_000, le=120_000)
    database_lock_timeout_ms: int = Field(default=3_000, ge=100, le=30_000)
    database_idle_transaction_timeout_ms: int = Field(default=60_000, ge=5_000, le=300_000)
    session_cookie_name: Literal["__Host-easyaudit_session"] = "__Host-easyaudit_session"
    session_ttl_seconds: int = Field(default=43_200, ge=300, le=2_592_000)

    @model_validator(mode="after")
    def validate_database_wait_budgets(self) -> "Settings":
        if self.database_lock_timeout_ms >= self.database_statement_timeout_ms:
            raise ValueError("database_lock_timeout_ms must be less than statement timeout")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
