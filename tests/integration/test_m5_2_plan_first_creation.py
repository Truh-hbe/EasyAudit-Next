from collections.abc import Iterator
from datetime import UTC, datetime
from os import environ
from uuid import uuid4

import pytest
from pwdlib import PasswordHash
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from easyaudit_next.api.dependencies import get_database_session
from easyaudit_next.api.review_contracts import ReviewCaseResponse
from easyaudit_next.cli import publish_scenario_in_session
from easyaudit_next.main import create_app
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.persistence.models import (
    LocalCredentialRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.review_core.domain.models import ScenarioKey, ScenarioVersion

if environ.get("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
    pytestmark = pytest.mark.skip(reason="PostgreSQL integration tests are opt-in outside CI")

PASSWORD = "m5-2-integration-password-000"
PASSWORD_HASH = PasswordHash.recommended()
NOW = datetime(2026, 8, 30, 1, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    engine = create_engine(environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_user(engine: Engine) -> tuple[OrganizationId, UserId, str]:
    organization_id = OrganizationId(uuid4())
    user_id = UserId(uuid4())
    login_name = f"m52-{user_id.hex}"
    with Session(engine) as session, session.begin():
        session.add(OrganizationRecord(id=organization_id, name=f"M5.2 {organization_id}"))
        session.flush()
        session.add(
            UserRecord(
                id=user_id,
                organization_id=organization_id,
                display_name="M5.2 Integration User",
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
    return organization_id, user_id, login_name


def _publish(engine: Engine, organization_id: OrganizationId, key: str) -> None:
    with Session(engine) as session, session.begin():
        publish_scenario_in_session(
            session,
            organization_id,
            ScenarioKey(key),
            ScenarioVersion(1),
        )


def _client(engine: Engine):
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


def test_plan_first_creation_reuses_checkpoint_and_exact_case_contract(
    postgres_engine: Engine,
) -> None:
    organization_id, user_id, login_name = _seed_user(postgres_engine)
    _publish(postgres_engine, organization_id, "process_review")
    _publish(postgres_engine, organization_id, "compliance_review")

    client = _client(postgres_engine)
    login = client.post(
        "/api/v1/auth/login",
        json={"login_name": login_name, "password": PASSWORD},
    )
    assert login.status_code == 200

    catalog = client.get("/api/v1/review-catalog")
    assert catalog.status_code == 200
    assert {(item["scenario_key"], item["scenario_version"]) for item in catalog.json()} == {
        ("process_review", 1),
        ("compliance_review", 1),
    }

    plan_response = client.post(
        "/api/v1/review-plans",
        json={"title": "M5.2 Integration Plan"},
    )
    assert plan_response.status_code == 201
    plan_id = plan_response.json()["id"]
    assert client.get(f"/api/v1/review-plans/{plan_id}").status_code == 200

    rejected = client.post(
        "/api/v1/review-cases",
        json={
            "plan_id": plan_id,
            "scenario_key": "process_review",
            "scenario_version": 1,
            "title": "M5.2 Invalid Case",
            "scenario_data": {"area_code": "area-a"},
        },
    )
    assert rejected.status_code == 422

    created = client.post(
        "/api/v1/review-cases",
        json={
            "plan_id": plan_id,
            "scenario_key": "process_review",
            "scenario_version": 1,
            "title": "M5.2 Valid Case",
            "scenario_data": {"area_code": "area-a", "review_type": "standard"},
        },
    )
    assert created.status_code == 201
    case = ReviewCaseResponse.model_validate(created.json())
    assert str(case.plan_id) == plan_id
    assert str(case.created_by) == str(user_id)
    assert case.planned_start_at is None
    assert case.planned_end_at is None
    assert case.scenario_data == {"area_code": "area-a", "review_type": "standard"}
