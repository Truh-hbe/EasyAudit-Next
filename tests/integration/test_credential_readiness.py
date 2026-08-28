import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from easyaudit_next.api.dependencies import get_database_session
from easyaudit_next.main import create_app
from easyaudit_next.platform.application.authentication import (
    AuthenticationService,
    InvalidCredentialsError,
    InvalidCurrentPasswordError,
    InvalidSessionError,
)
from easyaudit_next.platform.domain.ids import UserId
from easyaudit_next.platform.domain.models import PlatformAuditEvent
from easyaudit_next.platform.persistence.models import (
    AuthSessionRecord,
    LocalCredentialRecord,
    OrganizationRecord,
    PlatformAuditEventRecord,
    UserRecord,
)
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyAuthSessionRepository,
    SqlAlchemyLocalCredentialRepository,
    SqlAlchemyPlatformAuditRepository,
    SqlAlchemyUserRepository,
)

COOKIE_NAME = "__Host-easyaudit_session"
P0 = "initial-password-000"
P1 = "replacement-password-111"
P2 = "replacement-password-222"
PASSWORD_HASH = PasswordHash.recommended()


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_local_user(
    engine: Engine,
    *,
    platform_role: str = "ordinary_user",
    must_change_password: bool = True,
    password: str = P0,
) -> tuple[UUID, UUID, str]:
    organization_id = uuid4()
    user_id = uuid4()
    login_name = f"user-{user_id.hex}"
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        session.add(
            OrganizationRecord(
                id=organization_id,
                name=f"Credential Readiness {organization_id}",
            )
        )
        session.flush()
        session.add(
            UserRecord(
                id=user_id,
                organization_id=organization_id,
                display_name="Credential User",
                platform_role=platform_role,
            )
        )
        session.flush()
        session.add(
            LocalCredentialRecord(
                user_id=user_id,
                organization_id=organization_id,
                login_name=login_name,
                password_hash=PASSWORD_HASH.hash(password),
                password_changed_at=now,
                must_change_password=must_change_password,
            )
        )
    return organization_id, user_id, login_name


def _seed_user_without_credential(engine: Engine) -> tuple[UUID, UUID]:
    organization_id = uuid4()
    user_id = uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            OrganizationRecord(
                id=organization_id,
                name=f"No Local Credential {organization_id}",
            )
        )
        session.flush()
        session.add(
            UserRecord(
                id=user_id,
                organization_id=organization_id,
                display_name="External Credential User",
                platform_role="ordinary_user",
            )
        )
    return organization_id, user_id


def _service(
    session: Session,
    *,
    credentials: SqlAlchemyLocalCredentialRepository | None = None,
    audit: object | None = None,
) -> AuthenticationService:
    audit_repository = (
        audit if audit is not None else SqlAlchemyPlatformAuditRepository(session)
    )
    return AuthenticationService(
        credentials or SqlAlchemyLocalCredentialRepository(session),
        SqlAlchemyAuthSessionRepository(session),
        SqlAlchemyUserRepository(session),
        audit_repository,  # type: ignore[arg-type]
        password_hash=PASSWORD_HASH,
    )


def _login(engine: Engine, login_name: str, password: str) -> tuple[str, UUID]:
    with Session(engine) as session:
        result = _service(session).login(login_name, password)
        session.commit()
        return result.token, UUID(str(result.auth_session.id))


def _https_client(engine: Engine) -> TestClient:
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


def _assert_invalid_token(engine: Engine, token: str) -> None:
    with Session(engine) as session:
        with pytest.raises(InvalidSessionError):
            _service(session).authenticate(token)


def _assert_valid_token(engine: Engine, token: str) -> None:
    with Session(engine) as session:
        auth_session, user = _service(session).authenticate(token)
        assert auth_session.user_id == user.id


def test_concurrent_password_changes_have_exactly_one_winner(
    postgres_engine: Engine,
) -> None:
    _, user_id, login_name = _seed_local_user(postgres_engine)
    token_a, _ = _login(postgres_engine, login_name, P0)
    token_b, _ = _login(postgres_engine, login_name, P0)
    ready = Event()
    arrivals: list[str] = []

    def change(token: str, new_password: str) -> tuple[str, str | None]:
        with Session(postgres_engine) as session:
            service = _service(session)
            auth_session, user = service.authenticate(token)
            arrivals.append(token)
            if len(arrivals) == 2:
                ready.set()
            assert ready.wait(timeout=5)
            try:
                result = service.change_password(
                    auth_session,
                    user,
                    P0,
                    new_password,
                )
                session.commit()
                return "success", result.token
            except InvalidCurrentPasswordError:
                session.rollback()
                return "invalid-current", None

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(change, token_a, P1)
        future_b = pool.submit(change, token_b, P2)
        outcomes = [future_a.result(timeout=15), future_b.result(timeout=15)]

    assert sorted(outcome[0] for outcome in outcomes) == ["invalid-current", "success"]
    winning_token = next(token for status, token in outcomes if status == "success")
    assert winning_token is not None

    with Session(postgres_engine) as session:
        credential = session.get(LocalCredentialRecord, user_id)
        assert credential is not None
        matches = [
            PASSWORD_HASH.verify(candidate, credential.password_hash)
            for candidate in (P1, P2)
        ]
        assert matches.count(True) == 1
        assert credential.must_change_password is False

    _assert_invalid_token(postgres_engine, token_a)
    _assert_invalid_token(postgres_engine, token_b)
    _assert_valid_token(postgres_engine, winning_token)


class _PausingPasswordCredentialRepository(SqlAlchemyLocalCredentialRepository):
    def __init__(self, session: Session, locked: Event, release: Event) -> None:
        super().__init__(session)
        self._locked = locked
        self._release = release

    def lock_by_user_id(self, user_id: UserId):
        credential = super().lock_by_user_id(user_id)
        self._locked.set()
        assert self._release.wait(timeout=5)
        return credential


class _SignalingLoginCredentialRepository(SqlAlchemyLocalCredentialRepository):
    def __init__(self, session: Session, attempted: Event) -> None:
        super().__init__(session)
        self._attempted = attempted

    def lock_by_login_name(self, login_name: str):
        self._attempted.set()
        return super().lock_by_login_name(login_name)


def test_password_change_wins_before_stale_old_password_login(
    postgres_engine: Engine,
) -> None:
    _, _, login_name = _seed_local_user(postgres_engine)
    current_token, _ = _login(postgres_engine, login_name, P0)
    locked = Event()
    release = Event()
    login_attempted = Event()

    def change_password() -> str:
        with Session(postgres_engine) as session:
            credentials = _PausingPasswordCredentialRepository(session, locked, release)
            service = _service(session, credentials=credentials)
            auth_session, user = service.authenticate(current_token)
            result = service.change_password(auth_session, user, P0, P1)
            session.commit()
            return result.token

    def stale_login() -> bool:
        with Session(postgres_engine) as session:
            credentials = _SignalingLoginCredentialRepository(session, login_attempted)
            service = _service(session, credentials=credentials)
            try:
                service.login(login_name, P0)
            except InvalidCredentialsError:
                session.commit()
                return False
            session.commit()
            return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        change_future = pool.submit(change_password)
        assert locked.wait(timeout=5)
        login_future = pool.submit(stale_login)
        assert login_attempted.wait(timeout=5)
        release.set()
        rotated_token = change_future.result(timeout=15)
        stale_login_succeeded = login_future.result(timeout=15)

    assert stale_login_succeeded is False
    _assert_invalid_token(postgres_engine, current_token)
    _assert_valid_token(postgres_engine, rotated_token)

    with Session(postgres_engine) as session:
        service = _service(session)
        with pytest.raises(InvalidCredentialsError):
            service.login(login_name, P0)
        session.rollback()


class _PausingLoginCredentialRepository(SqlAlchemyLocalCredentialRepository):
    def __init__(self, session: Session, locked: Event, release: Event) -> None:
        super().__init__(session)
        self._locked = locked
        self._release = release

    def lock_by_login_name(self, login_name: str):
        credential = super().lock_by_login_name(login_name)
        self._locked.set()
        assert self._release.wait(timeout=5)
        return credential


class _SignalingPasswordCredentialRepository(SqlAlchemyLocalCredentialRepository):
    def __init__(self, session: Session, attempted: Event) -> None:
        super().__init__(session)
        self._attempted = attempted

    def lock_by_user_id(self, user_id: UserId):
        self._attempted.set()
        return super().lock_by_user_id(user_id)


def test_login_wins_then_password_change_revokes_newly_issued_session(
    postgres_engine: Engine,
) -> None:
    _, _, login_name = _seed_local_user(postgres_engine)
    current_token, _ = _login(postgres_engine, login_name, P0)
    login_locked = Event()
    release_login = Event()
    change_attempted = Event()

    def winning_login() -> str:
        with Session(postgres_engine) as session:
            credentials = _PausingLoginCredentialRepository(
                session,
                login_locked,
                release_login,
            )
            result = _service(session, credentials=credentials).login(login_name, P0)
            session.commit()
            return result.token

    def later_password_change() -> str:
        with Session(postgres_engine) as session:
            credentials = _SignalingPasswordCredentialRepository(
                session,
                change_attempted,
            )
            service = _service(session, credentials=credentials)
            auth_session, user = service.authenticate(current_token)
            result = service.change_password(auth_session, user, P0, P1)
            session.commit()
            return result.token

    with ThreadPoolExecutor(max_workers=2) as pool:
        login_future = pool.submit(winning_login)
        assert login_locked.wait(timeout=5)
        change_future = pool.submit(later_password_change)
        assert change_attempted.wait(timeout=5)
        release_login.set()
        issued_token = login_future.result(timeout=15)
        rotated_token = change_future.result(timeout=15)

    _assert_invalid_token(postgres_engine, issued_token)
    _assert_invalid_token(postgres_engine, current_token)
    _assert_valid_token(postgres_engine, rotated_token)


def test_stale_touch_cannot_resurrect_committed_revocation(
    postgres_engine: Engine,
) -> None:
    _, _, login_name = _seed_local_user(postgres_engine)
    token, _ = _login(postgres_engine, login_name, P0)
    token_hash = AuthenticationService.hash_token(token)
    later = datetime.now(UTC) + timedelta(minutes=1)

    with Session(postgres_engine) as stale_session:
        stale_repository = SqlAlchemyAuthSessionRepository(stale_session)
        stale = stale_repository.get_by_token_hash(token_hash)
        assert stale is not None

        with Session(postgres_engine) as revoker:
            revoked = SqlAlchemyAuthSessionRepository(revoker).revoke_if_active(
                stale.id,
                datetime.now(UTC),
            )
            assert revoked is True
            revoker.commit()

        touched = stale_repository.touch_if_active(
            stale.id,
            stale.token_hash,
            later,
        )
        assert touched is None
        stale_session.commit()

    with Session(postgres_engine) as session:
        row = session.get(AuthSessionRecord, UUID(str(stale.id)))
        assert row is not None
        assert row.revoked_at is not None
    _assert_invalid_token(postgres_engine, token)


def test_stale_pre_rotation_snapshot_cannot_restore_old_token_hash(
    postgres_engine: Engine,
) -> None:
    _, _, login_name = _seed_local_user(postgres_engine)
    token_t0, _ = _login(postgres_engine, login_name, P0)
    hash_t0 = AuthenticationService.hash_token(token_t0)
    token_t1 = f"rotated-{uuid4().hex}"
    hash_t1 = AuthenticationService.hash_token(token_t1)
    rotated_at = datetime.now(UTC)

    with Session(postgres_engine) as stale_session:
        stale_repository = SqlAlchemyAuthSessionRepository(stale_session)
        stale = stale_repository.get_by_token_hash(hash_t0)
        assert stale is not None

        with Session(postgres_engine) as rotator:
            rotated = SqlAlchemyAuthSessionRepository(rotator).rotate_if_active(
                stale.id,
                hash_t0,
                hash_t1,
                rotated_at,
            )
            assert rotated is not None
            rotator.commit()

        touched = stale_repository.touch_if_active(
            stale.id,
            stale.token_hash,
            rotated_at + timedelta(seconds=1),
        )
        assert touched is None
        stale_session.commit()

    with Session(postgres_engine) as session:
        row = session.get(AuthSessionRecord, UUID(str(stale.id)))
        assert row is not None
        assert row.token_hash == hash_t1
    _assert_invalid_token(postgres_engine, token_t0)
    _assert_valid_token(postgres_engine, token_t1)


def test_full_api_credential_remediation_journey(postgres_engine: Engine) -> None:
    _, admin_id, admin_login = _seed_local_user(
        postgres_engine,
        platform_role="system_admin",
        must_change_password=False,
        password="admin-password-000",
    )
    admin = _https_client(postgres_engine)
    login_admin = admin.post(
        "/api/v1/auth/login",
        json={"login_name": admin_login, "password": "admin-password-000"},
    )
    assert login_admin.status_code == 200
    assert login_admin.json()["user"]["id"] == str(admin_id)

    user_login = f"remediation-{uuid4().hex}"
    create_user = admin.post(
        "/api/v1/admin/users",
        json={
            "display_name": "Remediation User",
            "login_name": user_login,
            "initial_password": P0,
        },
    )
    assert create_user.status_code == 201
    user_id = UUID(create_user.json()["id"])

    client_a = _https_client(postgres_engine)
    client_b = _https_client(postgres_engine)
    login_a = client_a.post(
        "/api/v1/auth/login",
        json={"login_name": user_login, "password": P0},
    )
    login_b = client_b.post(
        "/api/v1/auth/login",
        json={"login_name": user_login, "password": P0},
    )
    assert login_a.status_code == 200
    assert login_b.status_code == 200
    session_a_id = UUID(login_a.json()["session_id"])
    session_b_id = UUID(login_b.json()["session_id"])
    token_t0 = client_a.cookies.get(COOKIE_NAME)
    token_b = client_b.cookies.get(COOKIE_NAME)
    assert token_t0
    assert token_b

    me_before = client_a.get("/api/v1/me")
    assert me_before.status_code == 200
    assert me_before.json()["must_change_password"] is True
    blocked = client_a.get("/api/v1/me/workbench")
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Password change required before business APIs"

    with Session(postgres_engine) as session:
        credential_before = session.get(LocalCredentialRecord, user_id)
        session_a_before = session.get(AuthSessionRecord, session_a_id)
        session_b_before = session.get(AuthSessionRecord, session_b_id)
        assert credential_before is not None
        assert session_a_before is not None
        assert session_b_before is not None
        password_hash_before = credential_before.password_hash
        password_changed_at_before = credential_before.password_changed_at
        session_a_hash_before = session_a_before.token_hash
        session_b_hash_before = session_b_before.token_hash

    wrong = client_a.post(
        "/api/v1/me/password",
        json={"current_password": "wrong-password", "new_password": P1},
    )
    assert wrong.status_code == 400
    short = client_a.post(
        "/api/v1/me/password",
        json={"current_password": P0, "new_password": "short"},
    )
    assert short.status_code == 422
    reused = client_a.post(
        "/api/v1/me/password",
        json={"current_password": P0, "new_password": P0},
    )
    assert reused.status_code == 422

    with Session(postgres_engine) as session:
        credential_after_failures = session.get(LocalCredentialRecord, user_id)
        session_a_after_failures = session.get(AuthSessionRecord, session_a_id)
        session_b_after_failures = session.get(AuthSessionRecord, session_b_id)
        assert credential_after_failures is not None
        assert session_a_after_failures is not None
        assert session_b_after_failures is not None
        assert credential_after_failures.password_hash == password_hash_before
        assert credential_after_failures.password_changed_at == password_changed_at_before
        assert credential_after_failures.must_change_password is True
        assert session_a_after_failures.token_hash == session_a_hash_before
        assert session_b_after_failures.token_hash == session_b_hash_before
        assert session_a_after_failures.revoked_at is None
        assert session_b_after_failures.revoked_at is None
        pre_success_password_events = session.scalar(
            select(func.count())
            .select_from(PlatformAuditEventRecord)
            .where(
                PlatformAuditEventRecord.target_user_id == user_id,
                PlatformAuditEventRecord.event_type == "auth.password_changed",
            )
        )
        assert pre_success_password_events == 0

    changed = client_a.post(
        "/api/v1/me/password",
        json={"current_password": P0, "new_password": P1},
    )
    assert changed.status_code == 200
    assert changed.json()["must_change_password"] is False
    token_t1 = client_a.cookies.get(COOKIE_NAME)
    assert token_t1
    assert token_t1 != token_t0
    assert token_t1 not in changed.text
    set_cookie = changed.headers["set-cookie"].lower()
    assert COOKIE_NAME.lower() in set_cookie
    assert "secure" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie
    assert "path=/" in set_cookie

    probe_t0 = _https_client(postgres_engine)
    old_current = probe_t0.get(
        "/api/v1/me",
        headers={"cookie": f"{COOKIE_NAME}={token_t0}"},
    )
    assert old_current.status_code == 401
    assert client_b.get("/api/v1/me").status_code == 401

    me_after = client_a.get("/api/v1/me")
    assert me_after.status_code == 200
    assert me_after.json()["must_change_password"] is False
    assert client_a.get("/api/v1/me/workbench").status_code == 200

    old_password = _https_client(postgres_engine).post(
        "/api/v1/auth/login",
        json={"login_name": user_login, "password": P0},
    )
    assert old_password.status_code == 401
    new_password = _https_client(postgres_engine).post(
        "/api/v1/auth/login",
        json={"login_name": user_login, "password": P1},
    )
    assert new_password.status_code == 200

    with Session(postgres_engine) as session:
        credential = session.get(LocalCredentialRecord, user_id)
        current = session.get(AuthSessionRecord, session_a_id)
        other = session.get(AuthSessionRecord, session_b_id)
        assert credential is not None
        assert current is not None
        assert other is not None
        assert credential.must_change_password is False
        assert PASSWORD_HASH.verify(P1, credential.password_hash)
        assert current.token_hash == AuthenticationService.hash_token(token_t1)
        assert current.revoked_at is None
        assert other.revoked_at is not None

        password_events = session.scalars(
            select(PlatformAuditEventRecord).where(
                PlatformAuditEventRecord.target_user_id == user_id,
                PlatformAuditEventRecord.event_type == "auth.password_changed",
            )
        ).all()
        assert len(password_events) == 1
        revocation_events = session.scalars(
            select(PlatformAuditEventRecord).where(
                PlatformAuditEventRecord.target_user_id == user_id,
                PlatformAuditEventRecord.event_type == "auth.session_revoked",
            )
        ).all()
        assert any(event.target_session_id == session_b_id for event in revocation_events)
        all_events = [*password_events, *revocation_events]
        all_metadata = repr([event.metadata_json for event in all_events])
        assert token_t0 not in all_metadata
        assert token_t1 not in all_metadata
        assert P0 not in all_metadata
        assert P1 not in all_metadata


class _FailOnPasswordChangedAudit:
    def __init__(self, delegate: SqlAlchemyPlatformAuditRepository) -> None:
        self._delegate = delegate

    def add(self, event: PlatformAuditEvent) -> None:
        if event.event_type == "auth.password_changed":
            raise RuntimeError("injected audit failure")
        self._delegate.add(event)


def test_password_change_failure_rolls_back_entire_security_transition(
    postgres_engine: Engine,
) -> None:
    _, user_id, login_name = _seed_local_user(postgres_engine)
    token_a, session_a_id = _login(postgres_engine, login_name, P0)
    token_b, session_b_id = _login(postgres_engine, login_name, P0)

    with Session(postgres_engine) as session:
        audit = _FailOnPasswordChangedAudit(SqlAlchemyPlatformAuditRepository(session))
        service = _service(session, audit=audit)
        auth_session, user = service.authenticate(token_a)
        with pytest.raises(RuntimeError, match="injected audit failure"):
            service.change_password(auth_session, user, P0, P1)
        session.rollback()

    with Session(postgres_engine) as session:
        credential = session.get(LocalCredentialRecord, user_id)
        current = session.get(AuthSessionRecord, session_a_id)
        other = session.get(AuthSessionRecord, session_b_id)
        assert credential is not None
        assert current is not None
        assert other is not None
        assert PASSWORD_HASH.verify(P0, credential.password_hash)
        assert credential.must_change_password is True
        assert current.token_hash == AuthenticationService.hash_token(token_a)
        assert current.revoked_at is None
        assert other.token_hash == AuthenticationService.hash_token(token_b)
        assert other.revoked_at is None
        password_event_count = session.scalar(
            select(func.count())
            .select_from(PlatformAuditEventRecord)
            .where(
                PlatformAuditEventRecord.target_user_id == user_id,
                PlatformAuditEventRecord.event_type == "auth.password_changed",
            )
        )
        assert password_event_count == 0

    _assert_valid_token(postgres_engine, token_a)
    _assert_valid_token(postgres_engine, token_b)
    rollback_login, _ = _login(postgres_engine, login_name, P0)
    _assert_valid_token(postgres_engine, rollback_login)


def test_no_local_credential_posture_and_password_command(
    postgres_engine: Engine,
) -> None:
    organization_id, user_id = _seed_user_without_credential(postgres_engine)
    raw_token = f"external-{uuid4().hex}"
    session_id = uuid4()
    now = datetime.now(UTC)
    with Session(postgres_engine) as session, session.begin():
        session.add(
            AuthSessionRecord(
                id=session_id,
                organization_id=organization_id,
                user_id=user_id,
                token_hash=AuthenticationService.hash_token(raw_token),
                expires_at=now + timedelta(hours=1),
                last_seen_at=now,
                created_at=now,
            )
        )

    client = _https_client(postgres_engine)
    headers = {"cookie": f"{COOKIE_NAME}={raw_token}"}
    me = client.get("/api/v1/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["must_change_password"] is False

    change = client.post(
        "/api/v1/me/password",
        headers=headers,
        json={"current_password": P0, "new_password": P1},
    )
    assert change.status_code == 409
    assert change.json()["detail"] == "Local credential is unavailable"

    with Session(postgres_engine) as session:
        assert session.get(LocalCredentialRecord, user_id) is None
