from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from easyaudit_next.api.dependencies import get_application_engine
from easyaudit_next.infrastructure.database import create_database_engine
from easyaudit_next.main import create_app
from easyaudit_next.platform.settings import Settings

CODE_HEAD = "20260827_0011"


@pytest.fixture(scope="module")
def postgres_url() -> str:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    return os.environ["DATABASE_URL"]


@pytest.fixture
def bounded_engine(postgres_url: str) -> Iterator[Engine]:
    engine = create_database_engine(Settings(database_url=postgres_url))
    yield engine
    engine.dispose()


def test_postgresql_session_budgets_are_applied_centrally(bounded_engine: Engine) -> None:
    with bounded_engine.connect() as connection:
        assert connection.scalar(text("SHOW statement_timeout")) == "15s"
        assert connection.scalar(text("SHOW lock_timeout")) == "3s"
        assert connection.scalar(text("SHOW idle_in_transaction_session_timeout")) == "1min"


def test_pool_timeout_has_no_overflow(postgres_url: str) -> None:
    engine = create_database_engine(
        Settings(
            database_url=postgres_url,
            database_pool_size=1,
            database_pool_timeout_seconds=1,
        )
    )
    try:
        with engine.connect():
            with pytest.raises(SQLAlchemyTimeoutError):
                engine.connect()
        assert engine.pool.size() == 1  # type: ignore[attr-defined]
        assert engine.pool.overflow() <= 0  # type: ignore[attr-defined]
    finally:
        engine.dispose()


def test_statement_timeout_cancels_real_postgresql_work(postgres_url: str) -> None:
    engine = create_database_engine(
        Settings(database_url=postgres_url, database_statement_timeout_ms=1_000)
    )
    try:
        with engine.connect() as connection:
            with pytest.raises(OperationalError):
                connection.execute(text("SELECT pg_sleep(2)"))
    finally:
        engine.dispose()


def test_lock_timeout_bounds_real_conflicting_lock(postgres_url: str) -> None:
    engine = create_database_engine(
        Settings(
            database_url=postgres_url,
            database_lock_timeout_ms=500,
            database_statement_timeout_ms=5_000,
        )
    )
    first = engine.connect()
    second = engine.connect()
    try:
        first.execute(text("SELECT pg_advisory_lock(982451653)"))
        with pytest.raises(OperationalError):
            second.execute(text("SELECT pg_advisory_lock(982451653)"))
        second.rollback()
    finally:
        first.execute(text("SELECT pg_advisory_unlock(982451653)"))
        first.close()
        second.close()
        engine.dispose()


def test_readiness_is_200_only_for_exact_database_head(bounded_engine: Engine) -> None:
    app = create_app()
    app.dependency_overrides[get_application_engine] = lambda: bounded_engine
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_fails_closed_for_unexpected_database_head(postgres_url: str) -> None:
    administration = create_engine(postgres_url, pool_pre_ping=True)
    candidate = create_database_engine(Settings(database_url=postgres_url))
    try:
        with administration.begin() as connection:
            current = connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert current == CODE_HEAD
            connection.execute(
                text("UPDATE alembic_version SET version_num = 'unexpected_future_head'")
            )
        app = create_app()
        app.dependency_overrides[get_application_engine] = lambda: candidate
        with TestClient(app) as client:
            response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"detail": "Database schema is not ready"}
    finally:
        with administration.begin() as connection:
            connection.execute(
                text("UPDATE alembic_version SET version_num = :head"),
                {"head": CODE_HEAD},
            )
        candidate.dispose()
        administration.dispose()
