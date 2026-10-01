from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, make_url
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
        connect_args=business_connect_args(resolved),
    )


def business_connect_args(settings: Settings) -> dict[str, Any]:
    """libpq parameters of the business engine, merged with (never replacing) the URL's own.

    Timeouts via `options`; client-side limits for an unreachable or dead peer:
    `connect_timeout` bounds connection setup, TCP keepalives plus `tcp_user_timeout` detect a
    connection that went silent afterwards. A parameter already present in the URL
    wins (operator's explicit choice; `connect_timeout=0` means wait forever). Whether keepalive
    and `tcp_user_timeout` take effect depends on the platform's socket options (see libpq
    docs). TCP liveness is not a query-response deadline.
    """
    existing = _url_connect_kwargs(settings.database_url)
    args: dict[str, Any] = {
        "options": _with_options(
            _opt(existing.get("options")), **expected_server_settings(settings)
        )
    }
    limits = {
        "connect_timeout": settings.db_connect_timeout_seconds,
        "keepalives": 1,
        "keepalives_idle": settings.db_keepalives_idle_seconds,
        "keepalives_interval": settings.db_keepalives_interval_seconds,
        "keepalives_count": settings.db_keepalives_count,
        "tcp_user_timeout": settings.db_tcp_user_timeout_ms,
    }
    args.update({key: value for key, value in limits.items() if key not in existing})
    return args


def expected_server_settings(settings: Settings) -> dict[str, int]:
    """Server-side values (pg_settings, milliseconds) every business connection must have."""
    return {
        "statement_timeout": settings.db_statement_timeout_ms,
        "lock_timeout": settings.db_lock_timeout_ms,
        "idle_in_transaction_session_timeout": settings.db_idle_in_transaction_timeout_ms,
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


def _url_connect_kwargs(database_url: str) -> dict[str, Any]:
    url = make_url(database_url)
    _, raw_kwargs = url.get_dialect()().create_connect_args(url)
    return dict(raw_kwargs)


def _opt(options: object) -> str | None:
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


@contextmanager
def snapshot_read(session: Session) -> Iterator[None]:
    """Run the enclosed reads in one ``REPEATABLE READ, READ ONLY`` transaction.

    Under READ COMMITTED every statement takes its own snapshot, so a multi-query projection can
    mix states from before and after a concurrent commit. Isolation can only be chosen before
    the transaction's first statement, but the request transaction has already authenticated
    the caller, so the pending (read-only) work is committed first and the snapshot reuses the
    same pooled connection. The snapshot is committed on exit so later writes in the request
    (the session touch) start a fresh read-write transaction.
    """
    session.commit()
    session.connection(
        execution_options={"isolation_level": "REPEATABLE READ", "postgresql_readonly": True}
    )
    try:
        yield
    except BaseException:
        session.rollback()
        raise
    session.commit()
