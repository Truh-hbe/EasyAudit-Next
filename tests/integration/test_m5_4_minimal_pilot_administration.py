from __future__ import annotations

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from easyaudit_next.api.dependencies import get_database_session
from easyaudit_next.main import create_app
from easyaudit_next.platform.application.administration import PlatformAdministrationService
from easyaudit_next.platform.application.authentication import (
    AuthenticationService,
    InvalidCredentialsError,
)
from easyaudit_next.platform.application.services import IdentityOrganizationService
from easyaudit_next.platform.domain.ids import UserId
from easyaudit_next.platform.persistence.models import (
    AuthSessionRecord,
    LocalCredentialRecord,
    OrganizationRecord,
    PlatformAuditEventRecord,
    UserRecord,
)
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyAuthSessionRepository,
    SqlAlchemyDepartmentRepository,
    SqlAlchemyLocalCredentialRepository,
    SqlAlchemyOrganizationRepository,
    SqlAlchemyPlatformAuditRepository,
    SqlAlchemyUserRepository,
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


def _authentication_service(
    session: Session,
    *,
    credentials: SqlAlchemyLocalCredentialRepository | None = None,
    audit: object | None = None,
) -> AuthenticationService:
    return AuthenticationService(
        credentials or SqlAlchemyLocalCredentialRepository(session),
        SqlAlchemyAuthSessionRepository(session),
        SqlAlchemyUserRepository(session),
        audit if audit is not None else SqlAlchemyPlatformAuditRepository(session),  # type: ignore[arg-type]
        password_hash=PASSWORD_HASH,
    )


def _administration_service(
    session: Session,
    *,
    credentials: SqlAlchemyLocalCredentialRepository | None = None,
    audit: object | None = None,
) -> PlatformAdministrationService:
    organizations = SqlAlchemyOrganizationRepository(session)
    departments = SqlAlchemyDepartmentRepository(session)
    users = SqlAlchemyUserRepository(session)
    credential_repository = credentials or SqlAlchemyLocalCredentialRepository(session)
    audit_repository = audit if audit is not None else SqlAlchemyPlatformAuditRepository(session)
    return PlatformAdministrationService(
        IdentityOrganizationService(organizations, departments, users),
        organizations,
        departments,
        users,
        credential_repository,
        _authentication_service(session, credentials=credential_repository, audit=audit_repository),
        audit_repository,  # type: ignore[arg-type]
        password_hash=PASSWORD_HASH,
    )


def _login(engine: Engine, login_name: str, password: str) -> tuple[str, UUID]:
    with Session(engine) as session:
        result = _authentication_service(session).login(login_name, password)
        session.commit()
        return result.token, UUID(str(result.auth_session.id))


class _PausingUserCredentialRepository(SqlAlchemyLocalCredentialRepository):
    def __init__(self, session: Session, locked: Event, release: Event) -> None:
        super().__init__(session)
        self._locked = locked
        self._release = release

    def lock_by_user_id(self, user_id: UserId):
        credential = super().lock_by_user_id(user_id)
        self._locked.set()
        assert self._release.wait(timeout=10)
        return credential


class _SignalingUserCredentialRepository(SqlAlchemyLocalCredentialRepository):
    def __init__(self, session: Session, attempted: Event) -> None:
        super().__init__(session)
        self._attempted = attempted

    def lock_by_user_id(self, user_id: UserId):
        self._attempted.set()
        return super().lock_by_user_id(user_id)


class _PausingLoginCredentialRepository(SqlAlchemyLocalCredentialRepository):
    def __init__(self, session: Session, attempted: Event) -> None:
        super().__init__(session)
        self._attempted = attempted

    def lock_by_login_name(self, login_name: str):
        self._attempted.set()
        return super().lock_by_login_name(login_name)


class _FailOnCredentialResetAudit:
    def __init__(self, delegate: SqlAlchemyPlatformAuditRepository) -> None:
        self._delegate = delegate

    def add(self, event: object) -> None:
        if getattr(event, "event_type", None) == "admin.user_credential_reset":
            raise RuntimeError("injected credential reset audit failure")
        self._delegate.add(event)  # type: ignore[arg-type]


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
        reset_metadata = json.dumps(reset_events[0].metadata_json, sort_keys=True)
        assert TEMPORARY_PASSWORD not in reset_metadata
        assert credential.password_hash not in reset_metadata
        sessions = session.scalars(
            select(AuthSessionRecord).where(AuthSessionRecord.user_id == fixture.target_id)
        ).all()
        assert any(item.revoked_at is not None for item in sessions)


def test_reset_vs_stale_old_password_login_serializes_on_credential_row(
    postgres_engine: Engine,
) -> None:
    fixture = _seed(postgres_engine)
    old_token, old_session_id = _login(postgres_engine, fixture.target_login, TARGET_PASSWORD)
    reset_locked = Event()
    release_reset = Event()
    login_attempted = Event()

    def reset() -> None:
        with Session(postgres_engine) as session:
            credentials = _PausingUserCredentialRepository(session, reset_locked, release_reset)
            service = _administration_service(session, credentials=credentials)
            admin = SqlAlchemyUserRepository(session).get(fixture.admin_id)
            assert admin is not None
            service.reset_local_credential(admin, fixture.target_id, TEMPORARY_PASSWORD, now=NOW)
            session.commit()

    def stale_login() -> bool:
        with Session(postgres_engine) as session:
            credentials = _PausingLoginCredentialRepository(session, login_attempted)
            auth = _authentication_service(session, credentials=credentials)
            try:
                auth.login(fixture.target_login, TARGET_PASSWORD, now=NOW)
            except InvalidCredentialsError:
                session.commit()
                return False
            session.commit()
            return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        reset_future = pool.submit(reset)
        assert reset_locked.wait(timeout=10)
        login_future = pool.submit(stale_login)
        assert login_attempted.wait(timeout=10)
        release_reset.set()
        reset_future.result(timeout=20)
        assert login_future.result(timeout=20) is False

    with Session(postgres_engine) as session:
        credential = session.get(LocalCredentialRecord, fixture.target_id)
        old_session = session.get(AuthSessionRecord, old_session_id)
        assert credential is not None
        assert old_session is not None
        assert PASSWORD_HASH.verify(TEMPORARY_PASSWORD, credential.password_hash)
        assert not PASSWORD_HASH.verify(TARGET_PASSWORD, credential.password_hash)
        assert credential.must_change_password is True
        assert old_session.revoked_at is not None

    _assert_invalid_login(postgres_engine, fixture.target_login, TARGET_PASSWORD)


def _assert_invalid_login(engine: Engine, login_name: str, password: str) -> None:
    with Session(engine) as session:
        with pytest.raises(InvalidCredentialsError):
            _authentication_service(session).login(login_name, password, now=NOW)
        session.rollback()


def test_reset_after_password_change_revokes_rotated_session_and_wins(
    postgres_engine: Engine,
) -> None:
    fixture = _seed(postgres_engine)
    current_token, current_session_id = _login(
        postgres_engine,
        fixture.target_login,
        TARGET_PASSWORD,
    )
    password_change_locked = Event()
    release_password_change = Event()
    reset_attempted = Event()
    changed_password = "m5-4-changed-password-111"

    def password_change() -> str:
        with Session(postgres_engine) as session:
            credentials = _PausingUserCredentialRepository(
                session,
                password_change_locked,
                release_password_change,
            )
            auth = _authentication_service(session, credentials=credentials)
            auth_session, user = auth.authenticate(current_token, now=NOW)
            result = auth.change_password(
                auth_session,
                user,
                TARGET_PASSWORD,
                changed_password,
                now=NOW,
            )
            session.commit()
            return result.token

    def reset() -> None:
        with Session(postgres_engine) as session:
            credentials = _SignalingUserCredentialRepository(session, reset_attempted)
            service = _administration_service(session, credentials=credentials)
            admin = SqlAlchemyUserRepository(session).get(fixture.admin_id)
            assert admin is not None
            service.reset_local_credential(admin, fixture.target_id, TEMPORARY_PASSWORD, now=NOW)
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        change_future = pool.submit(password_change)
        assert password_change_locked.wait(timeout=10)
        reset_future = pool.submit(reset)
        assert reset_attempted.wait(timeout=10)
        release_password_change.set()
        changed_token = change_future.result(timeout=20)
        reset_future.result(timeout=20)

    with Session(postgres_engine) as session:
        credential = session.get(LocalCredentialRecord, fixture.target_id)
        current_session = session.get(AuthSessionRecord, current_session_id)
        assert credential is not None
        assert current_session is not None
        assert PASSWORD_HASH.verify(TEMPORARY_PASSWORD, credential.password_hash)
        assert not PASSWORD_HASH.verify(changed_password, credential.password_hash)
        assert credential.must_change_password is True
        assert current_session.revoked_at is not None
        changed_session = session.scalar(
            select(AuthSessionRecord).where(
                AuthSessionRecord.token_hash == AuthenticationService.hash_token(changed_token)
            )
        )
        assert changed_session is not None and changed_session.revoked_at is not None


def test_credential_reset_audit_failure_rolls_back_hash_sessions_and_audit(
    postgres_engine: Engine,
) -> None:
    fixture = _seed(postgres_engine)
    old_token, old_session_id = _login(postgres_engine, fixture.target_login, TARGET_PASSWORD)

    with Session(postgres_engine) as session:
        before_audits = [
            (event.id, event.event_type, event.metadata_json)
            for event in session.scalars(
                select(PlatformAuditEventRecord).where(
                    PlatformAuditEventRecord.organization_id == fixture.organization_id
                ).order_by(PlatformAuditEventRecord.id)
            ).all()
        ]
        audit = _FailOnCredentialResetAudit(SqlAlchemyPlatformAuditRepository(session))
        service = _administration_service(session, audit=audit)
        admin = SqlAlchemyUserRepository(session).get(fixture.admin_id)
        assert admin is not None
        with pytest.raises(RuntimeError, match="injected credential reset audit failure"):
            service.reset_local_credential(
                admin,
                fixture.target_id,
                TEMPORARY_PASSWORD,
                now=NOW,
            )
        session.rollback()

    with Session(postgres_engine) as session:
        credential = session.get(LocalCredentialRecord, fixture.target_id)
        old_session = session.get(AuthSessionRecord, old_session_id)
        assert credential is not None
        assert old_session is not None
        assert PASSWORD_HASH.verify(TARGET_PASSWORD, credential.password_hash)
        assert credential.must_change_password is False
        assert old_session.revoked_at is None
        after_audits = [
            (event.id, event.event_type, event.metadata_json)
            for event in session.scalars(
                select(PlatformAuditEventRecord).where(
                    PlatformAuditEventRecord.organization_id == fixture.organization_id
                ).order_by(PlatformAuditEventRecord.id)
            ).all()
        ]
        assert after_audits == before_audits

    _login(postgres_engine, fixture.target_login, TARGET_PASSWORD)
    assert _authentication_service_for_token(postgres_engine, old_token) is True


def _authentication_service_for_token(engine: Engine, token: str) -> bool:
    with Session(engine) as session:
        auth = _authentication_service(session)
        auth_session, user = auth.authenticate(token, now=NOW)
        assert auth_session.user_id == user.id
        return True


def test_duplicate_login_name_returns_safe_409(postgres_engine: Engine) -> None:
    fixture = _seed(postgres_engine)
    admin = _client(postgres_engine)
    assert admin.post(
        "/api/v1/auth/login",
        json={"login_name": fixture.admin_login, "password": ADMIN_PASSWORD},
    ).status_code == 200

    response = admin.post(
        "/api/v1/admin/users",
        json={
            "display_name": "Duplicate login",
            "login_name": fixture.target_login,
            "initial_password": "m5-4-duplicate-password-000",
        },
    )

    assert response.status_code == 409
    for marker in ("INSERT", "SELECT", "password_hash", "$argon2", "parameters", "psycopg"):
        assert marker not in response.text
