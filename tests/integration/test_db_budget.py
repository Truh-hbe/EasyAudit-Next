"""Pilot-2B: connection budget and server-side timeouts on the business engine."""

import os
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from easyaudit_next.infrastructure.database import (
    create_database_engine,
    verify_server_settings,
)
from easyaudit_next.infrastructure.observability import RequestContextMiddleware
from easyaudit_next.platform.settings import Settings


@pytest.fixture(autouse=True)
def require_postgres() -> None:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")


CONFIGURED = Settings(
    db_statement_timeout_ms=7000,
    db_lock_timeout_ms=3000,
    db_idle_in_transaction_timeout_ms=11000,
)


def engine_with(**overrides: int | str) -> Engine:
    return create_database_engine(Settings(**overrides))  # type: ignore[arg-type]


@pytest.fixture
def engine() -> Iterator[Engine]:
    built = create_database_engine(CONFIGURED)
    yield built
    built.dispose()


def test_show_returns_the_configured_timeouts(engine: Engine) -> None:
    with engine.connect() as connection:
        shown = {
            name: connection.execute(text(f"SHOW {name}")).scalar_one()
            for name in ("statement_timeout", "lock_timeout", "idle_in_transaction_session_timeout")
        }

    assert shown == {
        "statement_timeout": "7s",
        "lock_timeout": "3s",
        "idle_in_transaction_session_timeout": "11s",
    }
    assert verify_server_settings(engine, CONFIGURED) == {}


def test_verification_reports_a_mismatch(engine: Engine) -> None:
    mismatches = verify_server_settings(
        engine,
        Settings(
            db_statement_timeout_ms=9000,
            db_lock_timeout_ms=3000,
            db_idle_in_transaction_timeout_ms=11000,
        ),
    )

    assert mismatches == {"statement_timeout": (9000, 7000)}


def test_existing_url_options_are_merged_not_replaced() -> None:
    base = Settings().database_url
    separator = "&" if "?" in base else "?"
    url = f"{base}{separator}options=-c%20application_name%3Dbudget_test"
    built = engine_with(database_url=url, db_statement_timeout_ms=7000)
    try:
        with built.connect() as connection:
            assert connection.execute(text("SHOW application_name")).scalar_one() == "budget_test"
            assert connection.execute(text("SHOW statement_timeout")).scalar_one() == "7s"
    finally:
        built.dispose()


def test_pool_limits_come_from_settings() -> None:
    built = engine_with(db_pool_size=3, db_max_overflow=2, db_pool_timeout_seconds=1.5)
    try:
        pool = built.pool
        assert (pool.size(), pool._max_overflow, pool._timeout) == (3, 2, 1.5)  # type: ignore[attr-defined]
    finally:
        built.dispose()


def test_statement_timeout_cancels_a_slow_query() -> None:
    built = engine_with(db_statement_timeout_ms=200)
    try:
        started = time.monotonic()
        with pytest.raises(OperationalError) as caught, built.connect() as connection:
            connection.execute(text("SELECT pg_sleep(5)"))
        assert isinstance(caught.value.orig, psycopg.errors.QueryCanceled)
        assert time.monotonic() - started < 3
    finally:
        built.dispose()


def test_migration_connection_is_not_subject_to_the_business_timeout() -> None:
    # alembic/env.py builds its own NullPool engine from the URL: no options are applied.
    env_source = (Path(__file__).parents[2] / "alembic" / "env.py").read_text()
    assert "create_database_engine" not in env_source
    assert "engine_from_config" in env_source

    migration_style = create_engine(Settings().database_url)
    business = engine_with(db_statement_timeout_ms=7000)
    try:
        with migration_style.connect() as connection:
            migrate_value = connection.execute(text("SHOW statement_timeout")).scalar_one()
            connection.execute(text("SELECT pg_sleep(0.3)"))
        with business.connect() as connection:
            assert connection.execute(text("SHOW statement_timeout")).scalar_one() == "7s"
        assert migrate_value != "7s"
    finally:
        migration_style.dispose()
        business.dispose()


@pytest.fixture
def probe_table(engine: Engine) -> Iterator[str]:
    name = f"db_budget_probe_{uuid4().hex[:8]}"
    with engine.begin() as connection:
        connection.execute(text(f"CREATE TABLE {name} (id int PRIMARY KEY)"))
        connection.execute(text(f"INSERT INTO {name} VALUES (1)"))
    yield name
    with engine.begin() as connection:
        connection.execute(text(f"DROP TABLE {name}"))


def test_second_session_fails_fast_when_the_row_lock_is_held(probe_table: str) -> None:
    holder = engine_with(db_lock_timeout_ms=5000)
    waiter = engine_with(db_lock_timeout_ms=300)
    try:
        with holder.connect() as a:
            a.execute(text(f"SELECT id FROM {probe_table} WHERE id = 1 FOR UPDATE"))
            started = time.monotonic()
            with pytest.raises(OperationalError) as caught, waiter.connect() as b:
                b.execute(text(f"SELECT id FROM {probe_table} WHERE id = 1 FOR UPDATE"))
            elapsed = time.monotonic() - started
            a.rollback()
        assert isinstance(caught.value.orig, psycopg.errors.LockNotAvailable)
        assert 0.25 <= elapsed < 3
    finally:
        holder.dispose()
        waiter.dispose()


def test_idle_in_transaction_connection_is_terminated_by_the_server() -> None:
    built = engine_with(db_idle_in_transaction_timeout_ms=300)
    try:
        with built.connect() as connection:
            connection.execute(text("SELECT 1"))  # opens a transaction and leaves it idle
            time.sleep(1.0)
            with pytest.raises(DBAPIError) as caught:
                connection.execute(text("SELECT 1"))
        assert isinstance(caught.value.orig, psycopg.errors.IdleInTransactionSessionTimeout)
    finally:
        built.dispose()


def _app_with_slow_route(route_engine: Engine, sql: str) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/slow")
    def slow() -> dict[str, str]:
        with Session(route_engine) as session:
            session.execute(text(sql))
        return {"ok": "yes"}

    return app


def test_statement_timeout_is_a_503_with_retry_after_and_no_details() -> None:
    built = engine_with(db_statement_timeout_ms=200)
    try:
        client = TestClient(_app_with_slow_route(built, "SELECT pg_sleep(5)"))
        response = client.get("/slow")
    finally:
        built.dispose()

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert set(response.json()) == {"detail", "request_id"}
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "pg_sleep" not in response.text


def test_lock_timeout_is_a_503_with_retry_after(probe_table: str) -> None:
    holder = engine_with(db_lock_timeout_ms=5000)
    waiter = engine_with(db_lock_timeout_ms=300)
    try:
        with holder.connect() as a:
            a.execute(text(f"SELECT id FROM {probe_table} FOR UPDATE"))
            client = TestClient(
                _app_with_slow_route(waiter, f"SELECT id FROM {probe_table} FOR UPDATE")
            )
            response = client.get("/slow")
            a.rollback()
    finally:
        holder.dispose()
        waiter.dispose()

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
