from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from easyaudit_next.api.dependencies import get_database_session
from easyaudit_next.main import create_app
from easyaudit_next.platform.persistence.models import (
    AuthSessionRecord,
    LocalCredentialRecord,
    OrganizationRecord,
    PlatformAuditEventRecord,
    UserRecord,
)
from easyaudit_next.review_core.persistence.models import ScenarioRecord, ScenarioVersionRecord

NOW = datetime(2026, 8, 30, 5, 0, tzinfo=UTC)
PASSWORD_HASH = PasswordHash.recommended()
ADMIN_PASSWORD = "m5-4-admin-password-000"
TARGET_PASSWORD = "m5-4-target-password-000"
TEMPORARY_PASSWORD = "m5-4-temporary-password-111"


@dataclass(frozen=True)
class AdminFixture:
    organization_id: UUID
    admin_id: UUID
    target_id: UUID
    foreign_target_id: UUID
    process_scenario_id: UUID
    compliance_scenario_id: UUID
    admin_login: str
    target_login: str


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed(engine: Engine) -> AdminFixture:
    organization_id = uuid4()
    foreign_organization_id = uuid4()
    admin_id = uuid4()
    target_id = uuid4()
    foreign_target_id = uuid4()
    process_scenario_id = uuid4()
    compliance_scenario_id = uuid4()
    process_version_id = uuid4()
    unsupported_version_id = uuid4()
    compliance_version_id = uuid4()
    admin_login = f"m54-admin-{admin_id.hex}"
    target_login = f"m54-target-{target_id.hex}"

    with Session(engine) as session, session.begin():
        session.add_all(
            [
                OrganizationRecord(id=organization_id, name=f"M5.4 {organization_id}"),
                OrganizationRecord(
                    id=foreign_organization_id,
                    name=f"M5.4 foreign {foreign_organization_id}",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                UserRecord(
                    id=admin_id,
                    organization_id=organization_id,
                    display_name="M5.4 System Administrator",
                    platform_role="system_admin",
                ),
                UserRecord(
                    id=target_id,
                    organization_id=organization_id,
                    display_name="M5.4 Target User",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=foreign_target_id,
                    organization_id=foreign_organization_id,
                    display_name="M5.4 Foreign Target",
                    platform_role="ordinary_user",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                LocalCredentialRecord(
                    user_id=admin_id,
                    organization_id=organization_id,
                    login_name=admin_login,
                    password_hash=PASSWORD_HASH.hash(ADMIN_PASSWORD),
                    password_changed_at=NOW,
                    must_change_password=False,
                ),
                LocalCredentialRecord(
                    user_id=target_id,
                    organization_id=organization_id,
                    login_name=target_login,
                    password_hash=PASSWORD_HASH.hash(TARGET_PASSWORD),
                    password_changed_at=NOW,
                    must_change_password=False,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                ScenarioRecord(
                    id=process_scenario_id,
                    organization_id=organization_id,
                    key="process_review",
                    name="Process Review",
                    is_active=True,
                ),
                ScenarioVersionRecord(
                    id=process_version_id,
                    scenario_id=process_scenario_id,
                    organization_id=organization_id,
                    version=1,
                    published_at=NOW,
                ),
                ScenarioVersionRecord(
                    id=unsupported_version_id,
                    scenario_id=process_scenario_id,
                    organization_id=organization_id,
                    version=99,
                    published_at=NOW,
                ),
                ScenarioRecord(
                    id=compliance_scenario_id,
                    organization_id=organization_id,
                    key="compliance_review",
                    name="Compliance Review",
                    is_active=False,
                ),
                ScenarioVersionRecord(
                    id=compliance_version_id,
                    scenario_id=compliance_scenario_id,
                    organization_id=organization_id,
                    version=1,
                    published_at=NOW,
                ),
            ]
        )
    return AdminFixture(
        organization_id=organization_id,
        admin_id=admin_id,
        target_id=target_id,
        foreign_target_id=foreign_target_id,
        process_scenario_id=process_scenario_id,
        compliance_scenario_id=compliance_scenario_id,
        admin_login=admin_login,
        target_login=target_login,
    )


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


def test_admin_status_is_exact_and_reset_revokes_old_sessions(
    postgres_engine: Engine,
) -> None:
    fixture = _seed(postgres_engine)
    admin = _client(postgres_engine)
    target = _client(postgres_engine)

    assert admin.get("/api/v1/admin/scenario-status").status_code == 401
    assert admin.post(
        "/api/v1/auth/login",
        json={"login_name": fixture.admin_login, "password": ADMIN_PASSWORD},
    ).status_code == 200
    target_login = target.post(
        "/api/v1/auth/login",
        json={"login_name": fixture.target_login, "password": TARGET_PASSWORD},
    )
    assert target_login.status_code == 200

    status_response = admin.get("/api/v1/admin/scenario-status")
    assert status_response.status_code == 200
    status_by_key = {item["scenario_key"]: item for item in status_response.json()["items"]}
    assert status_by_key["process_review"]["versions"] == [
        {
            "scenario_version": 1,
            "published_at": NOW.isoformat().replace("+00:00", "Z"),
            "registry_present": True,
            "ready": True,
        },
        {
            "scenario_version": 99,
            "published_at": NOW.isoformat().replace("+00:00", "Z"),
            "registry_present": False,
            "ready": False,
        },
    ]
    assert status_by_key["compliance_review"]["is_active"] is False
    assert status_by_key["compliance_review"]["versions"][0]["ready"] is False

    short_reset = admin.post(
        f"/api/v1/admin/users/{fixture.target_id}/credential-reset",
        json={"temporary_password": "short"},
    )
    assert short_reset.status_code == 422
    assert admin.get(f"/api/v1/admin/users/{fixture.target_id}").status_code == 200
    assert target.get("/api/v1/me").status_code == 200

    foreign_reset = admin.post(
        f"/api/v1/admin/users/{fixture.foreign_target_id}/credential-reset",
        json={"temporary_password": TEMPORARY_PASSWORD},
    )
    assert foreign_reset.status_code == 404

    reset = admin.post(
        f"/api/v1/admin/users/{fixture.target_id}/credential-reset",
        json={"temporary_password": TEMPORARY_PASSWORD},
    )
    assert reset.status_code == 200
    assert reset.json().keys() == {
        "id",
        "organization_id",
        "display_name",
        "platform_role",
        "primary_department_id",
        "is_active",
    }
    assert TEMPORARY_PASSWORD not in reset.text

    assert target.get("/api/v1/me").status_code == 401
    old_password_login = _client(postgres_engine).post(
        "/api/v1/auth/login",
        json={"login_name": fixture.target_login, "password": TARGET_PASSWORD},
    )
    assert old_password_login.status_code == 401
    temporary_password_login = _client(postgres_engine)
    assert temporary_password_login.post(
        "/api/v1/auth/login",
        json={"login_name": fixture.target_login, "password": TEMPORARY_PASSWORD},
    ).status_code == 200
    assert temporary_password_login.get("/api/v1/me").json()["must_change_password"] is True

    with Session(postgres_engine) as session:
        credential = session.get(LocalCredentialRecord, fixture.target_id)
        assert credential is not None
        assert not PASSWORD_HASH.verify(TARGET_PASSWORD, credential.password_hash)
        assert PASSWORD_HASH.verify(TEMPORARY_PASSWORD, credential.password_hash)
        assert credential.must_change_password is True
        reset_events = session.scalars(
            select(PlatformAuditEventRecord).where(
                PlatformAuditEventRecord.target_user_id == fixture.target_id,
                PlatformAuditEventRecord.event_type == "admin.user_credential_reset",
            )
        ).all()
        assert len(reset_events) == 1
        sessions = session.scalars(
            select(AuthSessionRecord).where(AuthSessionRecord.user_id == fixture.target_id)
        ).all()
        assert any(item.revoked_at is not None for item in sessions)
