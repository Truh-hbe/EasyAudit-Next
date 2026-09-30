"""Readiness checks. Results carry no detail; callers log failures with the request id.

Object storage is deliberately not checked: the application does not use it yet. Pilot-4A adds
it here together with Evidence upload.
"""

from collections.abc import Callable
from functools import lru_cache
from typing import Literal

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from easyaudit_next.infrastructure.observability import APP_LOGGER
from easyaudit_next.platform.settings import DEFAULT_DATABASE_URL, Settings, get_settings

CHECK_TIMEOUT_SECONDS = 2

CheckStatus = Literal["ok", "fail"]


@lru_cache
def get_readiness_engine() -> Engine:
    """Dedicated engine: short timeouts and no pooling, so probes never hold app connections."""
    return create_engine(
        get_settings().database_url,
        poolclass=NullPool,
        connect_args={
            "connect_timeout": CHECK_TIMEOUT_SECONDS,
            "options": f"-c statement_timeout={CHECK_TIMEOUT_SECONDS * 1000}",
        },
    )


@lru_cache
def get_expected_head() -> str:
    """Head of the alembic scripts shipped in this image (cwd holds alembic.ini, as for migrate)."""
    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    if head is None:
        raise RuntimeError("alembic scripts have no head")
    return head


def _log_failure(component: str, reason: str, exc: BaseException | None = None) -> None:
    APP_LOGGER.warning(
        "readiness_check_failed",
        extra={"fields": {"component": component, "reason": reason}},
        exc_info=exc,
    )


def check_configuration(settings: Settings) -> CheckStatus:
    try:
        make_url(settings.database_url)
    except Exception as exc:
        _log_failure("configuration", "database_url_invalid", exc)
        return "fail"
    if not settings.database_url:
        _log_failure("configuration", "database_url_missing")
        return "fail"
    if settings.app_env != "development" and settings.database_url == DEFAULT_DATABASE_URL:
        _log_failure("configuration", "database_url_is_development_default")
        return "fail"
    return "ok"


def check_database(engine: Engine) -> CheckStatus:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        _log_failure("database", "unreachable", exc)
        return "fail"
    return "ok"


def check_migrations(engine: Engine, expected_head: str) -> CheckStatus:
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_heads()
    except Exception as exc:
        _log_failure("migrations", "unreadable", exc)
        return "fail"
    if current != (expected_head,):
        APP_LOGGER.warning(
            "readiness_check_failed",
            extra={
                "fields": {
                    "component": "migrations",
                    "reason": "revision_mismatch",
                    "current_revision": list(current),
                    "expected_revision": expected_head,
                }
            },
        )
        return "fail"
    return "ok"


def run_readiness(
    settings: Settings, engine: Engine, expected_head: Callable[[], str]
) -> dict[str, CheckStatus]:
    checks: dict[str, CheckStatus] = {
        "configuration": check_configuration(settings),
        "database": check_database(engine),
        "migrations": "fail",
    }
    if checks["database"] == "ok":
        try:
            head = expected_head()
        except Exception as exc:
            _log_failure("migrations", "expected_head_unavailable", exc)
        else:
            checks["migrations"] = check_migrations(engine, head)
    return checks
