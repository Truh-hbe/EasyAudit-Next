from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
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
    login_throttle_window_seconds: int = Field(default=900, ge=60, le=86_400)
    login_throttle_login_name_limit: int = Field(default=5, ge=1)
    login_throttle_ip_limit: int = Field(default=50, ge=1)
    session_touch_interval_seconds: int = Field(default=300, ge=0, le=3600)
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=5, ge=0, le=100)
    db_pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    db_pool_recycle_seconds: int = Field(default=1800, ge=-1)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    db_tcp_user_timeout_ms: int = Field(default=15_000, ge=1_000)
    db_keepalives_idle_seconds: int = Field(default=10, ge=1)
    db_keepalives_interval_seconds: int = Field(default=5, ge=1)
    db_keepalives_count: int = Field(default=3, ge=1)
    db_statement_timeout_ms: int = Field(default=15_000, ge=1)
    db_lock_timeout_ms: int = Field(default=5_000, ge=1)
    db_idle_in_transaction_timeout_ms: int = Field(default=30_000, ge=1)
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    object_storage_endpoint: str = ""
    object_storage_bucket: str = "easyaudit-evidence"
    object_storage_region: str = "garage"
    # Credentials come from files (Docker secrets), never from the environment or the image.
    object_storage_access_key_id_file: str = ""
    object_storage_secret_access_key_file: str = ""
    object_storage_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    object_storage_read_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    object_storage_max_attempts: int = Field(default=3, ge=1, le=10)
    evidence_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    # Comma-separated; every entry must be a type the upload policy knows an extension for.
    evidence_allowed_content_types: str = (
        "application/pdf,image/png,image/jpeg,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
        "application/vnd.openxmlformats-officedocument.presentationml.presentation,"
        "text/plain,text/csv"
    )
    reminder_timezone: str = "Asia/Shanghai"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @model_validator(mode="after")
    def _pool_can_hold_two_connections(self) -> "Settings":
        # Minimum guard: a login briefly needs a second connection after another was released
        # (throttle transaction, then the request transaction); a 1-connection pool is a typo.
        if self.db_pool_size + self.db_max_overflow < 2:
            raise ValueError("DB_POOL_SIZE + DB_MAX_OVERFLOW must be at least 2")
        return self

    @field_validator("object_storage_endpoint")
    @classmethod
    def _endpoint_is_origin_only(cls, value: str) -> str:
        """http(s)://host[:port] and nothing else: no path prefix, query, fragment or userinfo.
        The readiness probe and the S3 client must agree on where the endpoint is."""
        if value == "":
            return value
        try:
            url = urlsplit(value)
            url.port  # noqa: B018 - raises ValueError for an invalid port
        except ValueError as exc:
            raise ValueError("OBJECT_STORAGE_ENDPOINT is not a valid URL") from exc
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
            or url.username is not None
            or url.password is not None
        ):
            raise ValueError(
                "OBJECT_STORAGE_ENDPOINT must be http(s)://host[:port] without path or credentials"
            )
        return value

    @field_validator("reminder_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("REMINDER_TIMEZONE must be an IANA timezone name") from exc
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
