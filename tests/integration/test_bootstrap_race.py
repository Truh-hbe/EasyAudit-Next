"""Two concurrent bootstraps must create at most one Organization (issue #87 B7).

Bootstrap requires a database without any Organization, so this runs in a throwaway database.
Both transactions pass the emptiness check; the hook after the check makes the interleaving
deterministic by holding the first one until the other arrives. Without serialization both write
and commit two Organizations. With the advisory lock the second blocks before its check, the wait
times out, the first commits and the second is refused.
"""

import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BrokenBarrierError
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

from easyaudit_next import cli
from easyaudit_next.cli import BootstrapRefusedError, bootstrap_admin_in_session
from easyaudit_next.platform.persistence.models import (
    LocalCredentialRecord,
    OrganizationRecord,
    PlatformAuditEventRecord,
    UserRecord,
)
from tests.integration.barrier_support import CountingBarrier

pytestmark = pytest.mark.skipif(
    os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1",
    reason="PostgreSQL integration tests are opt-in outside CI",
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "b7-bootstrap-race-password-000"
RENDEZVOUS_SECONDS = 1.5


@pytest.fixture
def clean_database_url() -> Iterator[str]:
    base_url = make_url(os.environ["DATABASE_URL"])
    name = f"easyaudit_b7_{uuid4().hex[:16]}"
    admin_engine = create_engine(
        base_url.set(database="postgres"), isolation_level="AUTOCOMMIT", pool_pre_ping=True
    )
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        url = base_url.set(database=name).render_as_string(hide_password=False)
        subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=REPOSITORY_ROOT,
            env={**os.environ, "DATABASE_URL": url},
            check=True,
            capture_output=True,
        )
        yield url
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin_engine.dispose()


@pytest.fixture
def engine(clean_database_url: str) -> Iterator[Engine]:
    engine = create_engine(clean_database_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


def _counts(engine: Engine) -> dict[str, int]:
    with Session(engine) as session:
        return {
            "organizations": session.query(OrganizationRecord).count(),
            "users": session.query(UserRecord).count(),
            "credentials": session.query(LocalCredentialRecord).count(),
            "audit": session.query(PlatformAuditEventRecord).count(),
        }


def test_concurrent_bootstraps_create_at_most_one_organization(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    barrier = CountingBarrier(2)
    real_validate: Callable[[str], Any] = cli.validate_local_password

    def validate_after_check(password: str) -> None:
        # `validate_local_password` runs right after the emptiness check, before any write.
        try:
            barrier.wait(RENDEZVOUS_SECONDS)
        except BrokenBarrierError:
            pass
        real_validate(password)

    monkeypatch.setattr(cli, "validate_local_password", validate_after_check)

    def bootstrap(index: int) -> Exception | None:
        try:
            with Session(engine) as session, session.begin():
                bootstrap_admin_in_session(
                    session, f"B7 Org {index}", f"B7 Admin {index}", f"b7-admin-{index}", PASSWORD
                )
        except Exception as exc:
            return exc
        return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(bootstrap, [1, 2]))

    failures = [outcome for outcome in outcomes if outcome is not None]
    assert len(failures) == 1
    assert isinstance(failures[0], BootstrapRefusedError)
    assert _counts(engine) == {"organizations": 1, "users": 1, "credentials": 1, "audit": 1}
    assert barrier.hits >= 1


def test_cli_refusal_exits_non_zero_with_readable_message(
    clean_database_url: str, engine: Engine
) -> None:
    with Session(engine) as session, session.begin():
        bootstrap_admin_in_session(session, "B7 Org", "B7 Admin", "b7-admin", PASSWORD)
    before = _counts(engine)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "easyaudit_next.cli",
            "bootstrap-admin",
            "--organization-name",
            "B7 Second",
            "--admin-name",
            "B7 Second Admin",
            "--login-name",
            "b7-second",
        ],
        cwd=REPOSITORY_ROOT,
        env={**os.environ, "DATABASE_URL": clean_database_url},
        input="",
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Bootstrap refused" in result.stderr
    assert "Traceback" not in result.stderr
    assert _counts(engine) == before
