"""M5.5 proof for clean PostgreSQL migration and first-run initialization."""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, make_url, select, text
from sqlalchemy.orm import Session

from easyaudit_next.api.dependencies import get_database_session
from easyaudit_next.cli import bootstrap_admin_in_session
from easyaudit_next.main import create_app
from easyaudit_next.platform.persistence.models import (
    LocalCredentialRecord,
    OrganizationRecord,
    PlatformAuditEventRecord,
    UserRecord,
)
from easyaudit_next.review_core.persistence.models import (
    ScenarioRecord,
    ScenarioVersionRecord,
)

pytestmark = pytest.mark.skipif(
    os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1",
    reason="PostgreSQL integration tests are opt-in outside CI",
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "m5-5-clean-initialization-password-000"


def _quoted_database_name(name: str) -> str:
    if not name.startswith("easyaudit_m55_") or not name.replace("_", "").isalnum():
        raise AssertionError(f"unexpected temporary database name: {name!r}")
    return f'"{name}"'


@pytest.fixture
def clean_database_url() -> Iterator[str]:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for the isolated PostgreSQL proof")
    base_url = make_url(database_url)
    database_name = f"easyaudit_m55_{uuid4().hex[:16]}"
    admin_engine = create_engine(
        base_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {_quoted_database_name(database_name)}"))
        yield base_url.set(database=database_name).render_as_string(hide_password=False)
    finally:
        with admin_engine.connect() as connection:
            connection.execute(
                text(f"DROP DATABASE {_quoted_database_name(database_name)} WITH (FORCE)")
            )
        admin_engine.dispose()


def _run_process(
    command: list[str],
    database_url: str,
    *,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=environment,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_success(
    command: list[str],
    database_url: str,
    *,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = _run_process(command, database_url, input_text=input_text)
    if result.returncode != 0:
        redacted_url = make_url(database_url).render_as_string(hide_password=True)
        safe_stdout = result.stdout.replace(database_url, redacted_url)
        safe_stderr = result.stderr.replace(database_url, redacted_url)
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{safe_stdout}\nstderr:\n{safe_stderr}"
        )
    return result


def _run_cli(
    database_url: str,
    *arguments: str,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return _run_process(
        [sys.executable, "-m", "easyaudit_next.cli", *arguments],
        database_url,
        input_text=input_text,
    )


def _counts(session: Session) -> dict[str, int]:
    return {
        "organizations": session.query(OrganizationRecord).count(),
        "users": session.query(UserRecord).count(),
        "credentials": session.query(LocalCredentialRecord).count(),
        "audit": session.query(PlatformAuditEventRecord).count(),
        "scenarios": session.query(ScenarioRecord).count(),
        "versions": session.query(ScenarioVersionRecord).count(),
    }


def test_clean_postgres_migration_bootstrap_and_exact_publication(
    clean_database_url: str,
) -> None:
    _run_success(["alembic", "upgrade", "head"], clean_database_url)
    engine = create_engine(clean_database_url, pool_pre_ping=True)
    organization_id: UUID
    try:
        with Session(engine) as session, session.begin():
            bootstrap_admin_in_session(
                session,
                "M5.5 Clean Initialization",
                "M5.5 Clean Administrator",
                "m55-clean-admin",
                PASSWORD,
            )
            organization = session.scalar(
                select(OrganizationRecord).where(
                    OrganizationRecord.name == "M5.5 Clean Initialization"
                )
            )
            assert organization is not None
            organization_id = organization.id
            assert _counts(session) == {
                "organizations": 1,
                "users": 1,
                "credentials": 1,
                "audit": 1,
                "scenarios": 0,
                "versions": 0,
            }

        for key in ("process_review", "compliance_review"):
            _run_success(
                [
                    sys.executable,
                    "-m",
                    "easyaudit_next.cli",
                    "publish-scenario",
                    "--organization-id",
                    str(organization_id),
                    "--key",
                    key,
                    "--version",
                    "1",
                ],
                clean_database_url,
            )

        with Session(engine) as session:
            assert _counts(session) == {
                "organizations": 1,
                "users": 1,
                "credentials": 1,
                "audit": 1,
                "scenarios": 2,
                "versions": 2,
            }
            scenarios = session.scalars(select(ScenarioRecord)).all()
            versions = session.scalars(select(ScenarioVersionRecord)).all()
            assert {
                (scenario.key, version.version)
                for scenario in scenarios
                for version in versions
                if version.scenario_id == scenario.id
            } == {("process_review", 1), ("compliance_review", 1)}

        duplicate = _run_cli(
            clean_database_url,
            "publish-scenario",
            "--organization-id",
            str(organization_id),
            "--key",
            "process_review",
            "--version",
            "1",
        )
        assert duplicate.returncode != 0

        unknown = _run_cli(
            clean_database_url,
            "publish-scenario",
            "--organization-id",
            str(organization_id),
            "--key",
            "process_review",
            "--version",
            "99",
        )
        assert unknown.returncode != 0

        with Session(engine) as session:
            before_repeat_bootstrap = _counts(session)
            with pytest.raises(RuntimeError, match="Bootstrap refused"):
                bootstrap_admin_in_session(
                    session,
                    "M5.5 Unexpected Second Organization",
                    "M5.5 Unexpected Second Administrator",
                    "m55-second-admin",
                    PASSWORD,
                )
            session.rollback()
            assert _counts(session) == before_repeat_bootstrap

        from fastapi.testclient import TestClient

        app = create_app()

        def database_session() -> Iterator[Session]:
            with Session(engine) as session:
                try:
                    yield session
                    session.commit()
                except Exception:
                    session.rollback()
                    raise

        app.dependency_overrides[get_database_session] = database_session
        with TestClient(app, base_url="https://testserver") as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"login_name": "m55-clean-admin", "password": PASSWORD},
            )
            assert login.status_code == 200
            status = client.get("/api/v1/admin/scenario-status")
            assert status.status_code == 200
            assert {
                (item["scenario_key"], item["versions"][0]["scenario_version"])
                for item in status.json()["items"]
            } == {("process_review", 1), ("compliance_review", 1)}
    finally:
        engine.dispose()
