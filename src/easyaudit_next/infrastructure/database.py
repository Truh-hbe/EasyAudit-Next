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
    return create_engine(resolved.database_url, pool_pre_ping=True)


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
        limit = f"-c statement_timeout={statement_timeout_ms}"
        existing = kwargs.get("options")
        kwargs["options"] = f"{existing} {limit}" if existing else limit
    return kwargs
