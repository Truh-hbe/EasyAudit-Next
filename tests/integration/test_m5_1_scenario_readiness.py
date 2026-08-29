from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from pwdlib import PasswordHash
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from easyaudit_next.api.dependencies import get_database_session
from easyaudit_next.cli import publish_scenario_in_session
from easyaudit_next.composition import build_review_planning_service
from easyaudit_next.main import create_app
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.persistence.models import (
    LocalCredentialRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.scenario_catalog import (
    ScenarioVersionAlreadyPublishedError,
)
from easyaudit_next.review_core.domain.models import ScenarioKey, ScenarioVersion
from easyaudit_next.review_core.persistence.models import (
    ScenarioRecord,
    ScenarioVersionRecord,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

NOW = datetime(2026, 8, 29, 9, 0, tzinfo=UTC)
PASSWORD = "ready-password-123"
PASSWORD_HASH = PasswordHash.recommended()


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_user(
    engine: Engine,
    *,
    must_change_password: bool = False,
) -> tuple[OrganizationId, UserId, str]:
    organization_id = OrganizationId(uuid4())
    user_id = UserId(uuid4())
    login_name = f"m51-{user_id.hex}"
    with Session(engine) as session, session.begin():
        session.add(
            OrganizationRecord(id=organization_id, name=f"M5.1 {organization_id}")
        )
        session.flush()
        session.add(
            UserRecord(
                id=user_id,
                organization_id=organization_id,
                display_name="M5.1 User",
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
                must_change_password=must_change_password,
            )
        )
    return organization_id, user_id, login_name


def _publish(
    engine: Engine,
    organization_id: OrganizationId,
    key: str,
    version: int,
) -> None:
    with Session(engine) as session, session.begin():
        publish_scenario_in_session(
            session,
            organization_id,
            ScenarioKey(key),
            ScenarioVersion(version),
        )


def _client(engine: Engine) -> TestClient:
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
    return TestClient(app, base_url="https://testserver")


def test_operator_publishes_exact_versions_and_is_organization_scoped(
    postgres_engine: Engine,
) -> None:
    organization_id, _, _ = _seed_user(postgres_engine)
    other_organization_id, _, _ = _seed_user(postgres_engine)

    _publish(postgres_engine, organization_id, "process_review", 1)
    _publish(postgres_engine, organization_id, "compliance_review", 1)

    with Session(postgres_engine) as session:
        own_keys = {
            (record.key, version.version)
            for record in session.scalars(
                select(ScenarioRecord).where(ScenarioRecord.organization_id == organization_id)
            )
            for version in session.scalars(
                select(ScenarioVersionRecord).where(
                    ScenarioVersionRecord.organization_id == organization_id,
                    ScenarioVersionRecord.scenario_id == record.id,
                )
            )
        }
        assert own_keys == {("process_review", 1), ("compliance_review", 1)}
        assert (
            session.scalars(
                select(ScenarioRecord).where(
                    ScenarioRecord.organization_id == other_organization_id
                )
            ).first()
            is None
        )

    with pytest.raises(ScenarioVersionAlreadyPublishedError):
        _publish(postgres_engine, organization_id, "process_review", 1)
    with pytest.raises(LookupError, match="unknown_review@1"):
        _publish(postgres_engine, organization_id, "unknown_review", 1)
    with pytest.raises(LookupError, match="does not exist"):
        _publish(postgres_engine, OrganizationId(uuid4()), "process_review", 1)


def test_catalog_matches_existing_case_creation_for_both_exact_scenarios(
    postgres_engine: Engine,
) -> None:
    organization_id, user_id, login_name = _seed_user(postgres_engine)
    _publish(postgres_engine, organization_id, "process_review", 1)
    _publish(postgres_engine, organization_id, "compliance_review", 1)

    client = _client(postgres_engine)
    assert client.get("/api/v1/review-catalog").status_code == 401
    login = client.post(
        "/api/v1/auth/login",
        json={"login_name": login_name, "password": PASSWORD},
    )
    assert login.status_code == 200

    catalog = client.get("/api/v1/review-catalog")
    assert catalog.status_code == 200
    assert catalog.json() == [
        {
            "scenario_key": "compliance_review",
            "scenario_version": 1,
            "display_name": "Compliance Review",
        },
        {
            "scenario_key": "process_review",
            "scenario_version": 1,
            "display_name": "Process Review",
        },
    ]

    process_case = client.post(
        "/api/v1/review-cases",
        json={
            "scenario_key": "process_review",
            "scenario_version": 1,
            "title": "Process pilot",
            "scenario_data": {"area_code": "area-a", "review_type": "standard"},
        },
    )
    compliance_case = client.post(
        "/api/v1/review-cases",
        json={
            "scenario_key": "compliance_review",
            "scenario_version": 1,
            "title": "Compliance pilot",
            "scenario_data": {
                "standard_reference": "standard-a",
                "scope_summary": "pilot scope",
            },
        },
    )
    assert process_case.status_code == 201
    assert compliance_case.status_code == 201
    assert process_case.json()["created_by"] == str(user_id)

    with Session(postgres_engine) as session:
        actor = SqlAlchemyUserRepository(session).get(user_id)
        assert actor is not None
        cases = build_review_planning_service(session).list_cases(actor)
        assert {case.scenario_key for case in cases} == {"process_review", "compliance_review"}


def test_must_change_password_user_cannot_read_business_catalog(
    postgres_engine: Engine,
) -> None:
    organization_id, _, login_name = _seed_user(postgres_engine, must_change_password=True)
    _publish(postgres_engine, organization_id, "process_review", 1)
    client = _client(postgres_engine)
    login = client.post(
        "/api/v1/auth/login",
        json={"login_name": login_name, "password": PASSWORD},
    )
    assert login.status_code == 200
    assert client.get("/api/v1/review-catalog").status_code == 403
