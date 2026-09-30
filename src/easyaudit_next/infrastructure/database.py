from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from easyaudit_next.platform.settings import Settings, get_settings


class Base(DeclarativeBase):
    """Shared SQLAlchemy metadata root; domain tables arrive through reviewed migrations."""


def create_database_engine(settings: Settings | None = None) -> Engine:
    resolved = settings or get_settings()
    return create_engine(
        resolved.database_url,
        pool_pre_ping=True,
        pool_size=resolved.db_pool_size,
        max_overflow=resolved.db_max_overflow,
        pool_timeout=resolved.db_pool_timeout_seconds,
        pool_recycle=resolved.db_pool_recycle_seconds,
        connect_args={
            "options": _with_options(
                _url_options(resolved.database_url), **expected_server_settings(resolved)
            )
        },
    )


def expected_server_settings(settings: Settings) -> dict[str, int]:
    """Server-side values (pg_settings, milliseconds) every business connection must have."""
    return {
        "statement_timeout": settings.db_statement_timeout_ms,
        "lock_timeout": settings.db_lock_timeout_ms,
        "idle_in_transaction_session_timeout": settings.db_idle_in_transaction_timeout_ms,
    }


def verify_server_settings(engine: Engine, settings: Settings) -> dict[str, tuple[int, int]]:
    """Mismatches `{name: (expected, actual)}` seen through the business engine; empty if fine.

    Blocking: call off the event loop.
    """
    expected = expected_server_settings(settings)
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT name, setting FROM pg_settings WHERE name = ANY(:names)"),
            {"names": list(expected)},
        ).all()
    actual = {name: int(value) for name, value in rows}
    return {
        name: (want, actual.get(name, -1))
        for name, want in expected.items()
        if actual.get(name) != want
    }


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _url_options(database_url: str) -> str | None:
    url = make_url(database_url)
    _, raw_kwargs = url.get_dialect()().create_connect_args(url)
    options = raw_kwargs.get("options")
    return str(options) if options else None


def _with_options(existing: str | None, **gucs: int) -> str:
    """Append `-c name=value` per setting to existing libpq options; later `-c` wins."""
    added = " ".join(f"-c {name}={value}" for name, value in gucs.items())
    return f"{existing} {added}" if existing else added


def libpq_connect_kwargs(
    database_url: str,
    *,
    connect_timeout: int | None = None,
    statement_timeout_ms: int | None = None,
) -> dict[str, Any]:
    """Connection parameters exactly as the business engine's dialect derives them.

    Uses the SQLAlchemy dialect's own URL translation, so host/port/credentials and every URL
    query parameter (`sslmode`, `sslrootcert`, a Unix-socket `host`, `options`, ...) reach
    libpq unchanged; readiness must reach the same target with the same TLS requirements as
    the business engine. Only the probe's own limits are applied on top; `options` is merged,
    not replaced.
    """
    url = make_url(database_url)
    _, raw_kwargs = url.get_dialect()().create_connect_args(url)
    kwargs = dict(raw_kwargs)
    if connect_timeout is not None:
        kwargs["connect_timeout"] = connect_timeout
    if statement_timeout_ms is not None:
        kwargs["options"] = _with_options(
            kwargs.get("options"), statement_timeout=statement_timeout_ms
        )
    return kwargs
