from collections.abc import Iterator
from datetime import UTC, datetime
from os import environ
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from easyaudit_next.api.dependencies import get_database_session
from easyaudit_next.cli import publish_scenario_in_session
from easyaudit_next.main import create_app
from easyaudit_next.platform.persistence.models import (
    LocalCredentialRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.review_core.domain.models import ScenarioKey, ScenarioVersion
from easyaudit_next.review_core.persistence.models import (
    ActivityRecord,
    CreateIdempotencyRecord,
    ReviewCaseRecord,
    ReviewPlanRecord,
)

PASSWORD = "pilot-3-idempotency-password-000"
PASSWORD_HASH = PasswordHash.recommended()
NOW = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
CASE_BODY = {
    "scenario_key": "process_review",
    "scenario_version": 1,
    "scenario_data": {"area_code": "area-a", "review_type": "standard"},
}

requires_postgres = pytest.mark.skipif(
    environ.get("EASYAUDIT_RUN_POSTGRES_TESTS") != "1",
    reason="PostgreSQL integration tests are opt-in outside CI",
)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    engine = create_engine(environ["DATABASE_URL"], pool_pre_ping=True, pool_size=10)
    yield engine
    engine.dispose()


def seed_org(engine: Engine, users: int = 1) -> tuple[UUID, list[tuple[UUID, str]]]:
    """A fresh Organization with published scenarios and `users` ordinary users."""

    organization_id = uuid4()
    seeded: list[tuple[UUID, str]] = []
    with Session(engine) as session, session.begin():
        session.add(OrganizationRecord(id=organization_id, name=f"P3 {organization_id}"))
        session.flush()
        for _ in range(users):
            user_id = uuid4()
            login_name = f"p3-{user_id.hex}"
            session.add(
                UserRecord(
                    id=user_id,
                    organization_id=organization_id,
                    display_name="Pilot-3 User",
                    platform_role="ordinary_user",
                )
            )
            session.flush()
            session.add(
                LocalCredentialRecord(
                    user_id=user_id,
                    organization_id=organization_id,
                    login_name=login_name,
                    password_hash=PASSWORD_HASH.hash(PASSWORD),
                    password_changed_at=NOW,
                    must_change_password=False,
                )
            )
            seeded.append((user_id, login_name))
        for key in ("process_review", "compliance_review"):
            publish_scenario_in_session(
                session, organization_id, ScenarioKey(key), ScenarioVersion(1)
            )
    return organization_id, seeded


def login(engine: Engine, login_name: str) -> TestClient:
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
    # Login throttle counts per client IP in the shared database: never reuse an address.
    ip = ".".join(str(uuid4().int % 250 + 1) for _ in range(4))
    client = TestClient(
        app, base_url="https://testserver", client=(ip, 50000), raise_server_exceptions=False
    )
    response = client.post(
        "/api/v1/auth/login", json={"login_name": login_name, "password": PASSWORD}
    )
    assert response.status_code == 200
    return client


def clone(client: TestClient) -> TestClient:
    """Another client of the same user (own thread/connection use, same session cookie)."""

    other = TestClient(client.app, base_url="https://testserver", raise_server_exceptions=False)
    other.cookies.update(client.cookies)
    return other


def count_plans(engine: Engine, organization_id: UUID, title: str) -> int:
    with Session(engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(ReviewPlanRecord)
            .where(
                ReviewPlanRecord.organization_id == organization_id,
                ReviewPlanRecord.title == title,
            )
        ) or 0


def count_cases(engine: Engine, organization_id: UUID, title: str) -> int:
    with Session(engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(ReviewCaseRecord)
            .where(
                ReviewCaseRecord.organization_id == organization_id,
                ReviewCaseRecord.title == title,
            )
        ) or 0


def count_activities(engine: Engine, organization_id: UUID) -> int:
    with Session(engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(ActivityRecord.organization_id == organization_id)
        ) or 0


def count_records(engine: Engine, organization_id: UUID) -> int:
    with Session(engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(CreateIdempotencyRecord)
            .where(CreateIdempotencyRecord.organization_id == organization_id)
        ) or 0
