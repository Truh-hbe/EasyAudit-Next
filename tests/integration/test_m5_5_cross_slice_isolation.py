"""M5.5 API proof for combined tenant and business-role boundaries."""

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import Engine, create_engine, select
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
    CaseMemberRecord,
    ReviewCaseRecord,
    ReviewPlanRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)

pytestmark = pytest.mark.skipif(
    os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1",
    reason="PostgreSQL integration tests are opt-in outside CI",
)

PASSWORD = "m5-5-isolation-password-000"
NOW = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
PASSWORD_HASH = PasswordHash.recommended()


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for the PostgreSQL proof")
    engine = create_engine(database_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


def _client(engine: Engine) -> TestClient:
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


def _seed(engine: Engine) -> dict[str, UUID | str]:
    organization_id = uuid4()
    foreign_organization_id = uuid4()
    ordinary_id = uuid4()
    inactive_id = uuid4()
    admin_id = uuid4()
    foreign_user_id = uuid4()
    own_case_id = uuid4()
    admin_case_id = uuid4()
    foreign_plan_id = uuid4()
    foreign_case_id = uuid4()
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                OrganizationRecord(id=organization_id, name=f"M5.5 API {organization_id}"),
                OrganizationRecord(
                    id=foreign_organization_id,
                    name=f"M5.5 Foreign API {foreign_organization_id}",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                UserRecord(
                    id=ordinary_id,
                    organization_id=organization_id,
                    display_name="M5.5 API Ordinary User",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=inactive_id,
                    organization_id=organization_id,
                    display_name="M5.5 API Inactive Candidate",
                    platform_role="ordinary_user",
                    is_active=False,
                ),
                UserRecord(
                    id=admin_id,
                    organization_id=organization_id,
                    display_name="M5.5 API System Admin",
                    platform_role="system_admin",
                ),
                UserRecord(
                    id=foreign_user_id,
                    organization_id=foreign_organization_id,
                    display_name="M5.5 API Foreign Candidate Name",
                    platform_role="ordinary_user",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                LocalCredentialRecord(
                    user_id=ordinary_id,
                    organization_id=organization_id,
                    login_name=f"m55-api-ordinary-{ordinary_id.hex}",
                    password_hash=PASSWORD_HASH.hash(PASSWORD),
                    password_changed_at=NOW,
                ),
                LocalCredentialRecord(
                    user_id=admin_id,
                    organization_id=organization_id,
                    login_name=f"m55-api-admin-{admin_id.hex}",
                    password_hash=PASSWORD_HASH.hash(PASSWORD),
                    password_changed_at=NOW,
                ),
            ]
        )
        session.flush()
        publish_scenario_in_session(
            session,
            organization_id,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
        )
        publish_scenario_in_session(
            session,
            organization_id,
            ScenarioKey("compliance_review"),
            ScenarioVersion(1),
        )
        publish_scenario_in_session(
            session,
            foreign_organization_id,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
        )
        session.flush()
        own_process_version_id = session.scalar(
            select(ScenarioVersionRecord)
            .join(ScenarioRecord, ScenarioRecord.id == ScenarioVersionRecord.scenario_id)
            .where(
                ScenarioVersionRecord.organization_id == organization_id,
                ScenarioRecord.key == "process_review",
                ScenarioVersionRecord.version == 1,
            )
        )
        foreign_process_version_id = session.scalar(
            select(ScenarioVersionRecord)
            .join(ScenarioRecord, ScenarioRecord.id == ScenarioVersionRecord.scenario_id)
            .where(
                ScenarioVersionRecord.organization_id == foreign_organization_id,
                ScenarioRecord.key == "process_review",
                ScenarioVersionRecord.version == 1,
            )
        )
        assert own_process_version_id is not None
        assert foreign_process_version_id is not None
        session.add_all(
            [
                ReviewCaseRecord(
                    id=own_case_id,
                    organization_id=organization_id,
                    plan_id=None,
                    scenario_version_id=own_process_version_id.id,
                    title="M5.5 API Own Case",
                    lifecycle="draft",
                    planned_start_at=None,
                    planned_end_at=None,
                    started_at=None,
                    fieldwork_completed_at=None,
                    closed_at=None,
                    scenario_data_json={"area_code": "M55", "review_type": "pilot"},
                    created_by=ordinary_id,
                    created_at=NOW,
                ),
                ReviewCaseRecord(
                    id=admin_case_id,
                    organization_id=organization_id,
                    plan_id=None,
                    scenario_version_id=own_process_version_id.id,
                    title="M5.5 API Admin Has No Case Role",
                    lifecycle="draft",
                    planned_start_at=None,
                    planned_end_at=None,
                    started_at=None,
                    fieldwork_completed_at=None,
                    closed_at=None,
                    scenario_data_json={"area_code": "M55", "review_type": "admin"},
                    created_by=admin_id,
                    created_at=NOW,
                ),
                ReviewPlanRecord(
                    id=foreign_plan_id,
                    organization_id=foreign_organization_id,
                    title="M5.5 API Foreign Plan",
                    planned_start_at=None,
                    planned_end_at=None,
                    created_by=foreign_user_id,
                    created_at=NOW,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                CaseMemberRecord(
                    organization_id=organization_id,
                    case_id=own_case_id,
                    user_id=ordinary_id,
                    role_key="lead",
                    joined_at=NOW,
                ),
                ReviewCaseRecord(
                    id=foreign_case_id,
                    organization_id=foreign_organization_id,
                    plan_id=foreign_plan_id,
                    scenario_version_id=foreign_process_version_id.id,
                    title="M5.5 API Foreign Case",
                    lifecycle="draft",
                    planned_start_at=None,
                    planned_end_at=None,
                    started_at=None,
                    fieldwork_completed_at=None,
                    closed_at=None,
                    scenario_data_json={"area_code": "FOREIGN", "review_type": "hidden"},
                    created_by=foreign_user_id,
                    created_at=NOW,
                ),
            ]
        )
        session.flush()
        session.add(
            CaseMemberRecord(
                organization_id=foreign_organization_id,
                case_id=foreign_case_id,
                user_id=foreign_user_id,
                role_key="lead",
                joined_at=NOW,
            )
        )
    return {
        "ordinary_login": f"m55-api-ordinary-{ordinary_id.hex}",
        "admin_login": f"m55-api-admin-{admin_id.hex}",
        "own_case_id": own_case_id,
        "admin_case_id": admin_case_id,
        "foreign_plan_id": foreign_plan_id,
        "foreign_case_id": foreign_case_id,
        "foreign_user_id": foreign_user_id,
    }


def test_api_combines_tenant_isolation_with_exact_business_authorization(
    postgres_engine: Engine,
) -> None:
    facts = _seed(postgres_engine)
    ordinary = _client(postgres_engine)
    admin = _client(postgres_engine)
    assert (
        ordinary.post(
            "/api/v1/auth/login",
            json={"login_name": facts["ordinary_login"], "password": PASSWORD},
        ).status_code
        == 200
    )
    assert (
        admin.post(
            "/api/v1/auth/login",
            json={"login_name": facts["admin_login"], "password": PASSWORD},
        ).status_code
        == 200
    )

    catalog = ordinary.get("/api/v1/review-catalog")
    assert catalog.status_code == 200
    assert {(item["scenario_key"], item["scenario_version"]) for item in catalog.json()} == {
        ("process_review", 1),
        ("compliance_review", 1),
    }
    assert "M5.5 Foreign" not in catalog.text

    for path in (
        f"/api/v1/review-plans/{facts['foreign_plan_id']}",
        f"/api/v1/review-cases/{facts['foreign_case_id']}",
    ):
        response = ordinary.get(path)
        assert response.status_code == 404
        assert "M5.5 API Foreign" not in response.text

    invalid_role = ordinary.get(
        f"/api/v1/review-cases/{facts['own_case_id']}/member-candidates",
        params={"role_key": "not-a-real-role", "q": "Foreign", "limit": 20},
    )
    assert invalid_role.status_code == 422
    assert "Foreign Candidate Name" not in invalid_role.text

    inactive = ordinary.get(
        f"/api/v1/review-cases/{facts['own_case_id']}/member-candidates",
        params={"role_key": "reviewer", "q": "Inactive Candidate", "limit": 20},
    )
    assert inactive.status_code == 200
    assert inactive.json() == []

    assert admin.get(f"/api/v1/review-cases/{facts['admin_case_id']}").status_code == 403
    foreign_admin = admin.get(f"/api/v1/admin/users/{facts['foreign_user_id']}")
    assert foreign_admin.status_code == 404
    foreign_admin_mutation = admin.patch(
        f"/api/v1/admin/users/{facts['foreign_user_id']}",
        json={"display_name": "should-not-change"},
    )
    assert foreign_admin_mutation.status_code == 404
    assert "Foreign Candidate Name" not in foreign_admin.text
    assert "Foreign Candidate Name" not in foreign_admin_mutation.text
