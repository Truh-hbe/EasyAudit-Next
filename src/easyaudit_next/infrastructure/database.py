from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from easyaudit_next.platform.settings import Settings, get_settings


class Base(DeclarativeBase):
    """Shared SQLAlchemy metadata root; domain tables arrive through reviewed migrations."""


def create_database_engine(settings: Settings | None = None) -> Engine:
    resolved = settings or get_settings()
    driver_options = " ".join(
        (
            f"-c statement_timeout={resolved.database_statement_timeout_ms}",
            f"-c lock_timeout={resolved.database_lock_timeout_ms}",
            "-c idle_in_transaction_session_timeout="
            f"{resolved.database_idle_transaction_timeout_ms}",
        )
    )
    # connect_args intentionally wins over any conflicting URL query parameter so the
    # reviewed application budget is authoritative for every new psycopg connection.
    return create_engine(
        resolved.database_url,
        pool_pre_ping=True,
        pool_size=resolved.database_pool_size,
        max_overflow=0,
        pool_timeout=resolved.database_pool_timeout_seconds,
        connect_args={
            "connect_timeout": resolved.database_connect_timeout_seconds,
            "options": driver_options,
        },
    )


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
