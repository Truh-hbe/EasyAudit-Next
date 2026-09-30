"""Pilot-2B: `last_seen_at` is written at most once per touch interval."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, update
from sqlalchemy.orm import Session

from easyaudit_next.main import create_app
from easyaudit_next.platform.application.authentication import AuthenticationService
from easyaudit_next.platform.persistence.models import AuthSessionRecord
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyAuthSessionRepository,
    SqlAlchemyLocalCredentialRepository,
    SqlAlchemyPlatformAuditRepository,
    SqlAlchemyUserRepository,
)
from tests.integration.test_credential_readiness import (
    COOKIE_NAME,
    P0,
    PASSWORD_HASH,
    _login,
    _seed_local_user,
)
from tests.integration.test_credential_readiness import (
    postgres_engine as postgres_engine,
)

INTERVAL = timedelta(seconds=300)


def _service(session: Session) -> AuthenticationService:
    return AuthenticationService(
        SqlAlchemyLocalCredentialRepository(session),
        SqlAlchemyAuthSessionRepository(session),
        SqlAlchemyUserRepository(session),
        SqlAlchemyPlatformAuditRepository(session),
        touch_interval=INTERVAL,
        password_hash=PASSWORD_HASH,
    )


def _row(engine: Engine, session_id: UUID) -> AuthSessionRecord:
    with Session(engine) as session:
        row = session.get(AuthSessionRecord, session_id)
        assert row is not None
        session.expunge(row)
        return row


def _touch(engine: Engine, token: str, session_id: UUID, at: datetime) -> int:
    """Run one touch; returns how many UPDATE auth_sessions statements it issued."""
    updates: list[str] = []

    def record(_c: object, _cur: object, statement: str, *_: object) -> None:
        if statement.lstrip().upper().startswith("UPDATE AUTH_SESSIONS"):
            updates.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with Session(engine) as session:
            service = _service(session)
            current, _ = service.authenticate(token, now=at)
            service.touch(current, now=at)
            session.commit()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return len(updates)


def test_touch_within_interval_issues_no_write_and_after_interval_updates(
    postgres_engine: Engine,
) -> None:
    _, _, login_name = _seed_local_user(postgres_engine)
    token, session_id = _login(postgres_engine, login_name, P0)
    logged_in_at = _row(postgres_engine, session_id).last_seen_at
    assert logged_in_at is not None

    within = logged_in_at + INTERVAL - timedelta(seconds=1)
    assert _touch(postgres_engine, token, session_id, within) == 0
    assert _row(postgres_engine, session_id).last_seen_at == logged_in_at

    after = logged_in_at + INTERVAL + timedelta(seconds=1)
    assert _touch(postgres_engine, token, session_id, after) == 1
    assert _row(postgres_engine, session_id).last_seen_at == after


def test_stale_snapshot_inside_the_interval_is_still_guarded_by_the_update_condition(
    postgres_engine: Engine,
) -> None:
    _, _, login_name = _seed_local_user(postgres_engine)
    token, session_id = _login(postgres_engine, login_name, P0)
    row = _row(postgres_engine, session_id)
    assert row.last_seen_at is not None
    recent = row.last_seen_at + INTERVAL * 2
    with Session(postgres_engine) as other, other.begin():
        other.execute(
            update(AuthSessionRecord)
            .where(AuthSessionRecord.id == session_id)
            .values(last_seen_at=recent)
        )

    # A request that loaded the session before `recent` was written still must not go back.
    with Session(postgres_engine) as session:
        stale = SqlAlchemyAuthSessionRepository(session).get(session_id)
        assert stale is not None and stale.last_seen_at == recent
    with Session(postgres_engine) as session:
        touched = SqlAlchemyAuthSessionRepository(session).touch_if_active(
            stale.id, stale.token_hash, recent + timedelta(seconds=10), min_interval=INTERVAL
        )
        assert touched is None
    assert _row(postgres_engine, session_id).last_seen_at == recent
    assert token


def test_revoked_and_expired_sessions_are_never_touched(postgres_engine: Engine) -> None:
    _, _, login_name = _seed_local_user(postgres_engine)
    token, session_id = _login(postgres_engine, login_name, P0)
    before = _row(postgres_engine, session_id)
    assert before.last_seen_at is not None
    far_later = before.last_seen_at + INTERVAL * 3

    with Session(postgres_engine) as session:
        service = _service(session)
        stale, _ = service.authenticate(token, now=far_later)
        # Expired at the moment of touching.
        service.touch(stale, now=before.expires_at + timedelta(seconds=1))
        session.commit()
    assert _row(postgres_engine, session_id).last_seen_at == before.last_seen_at

    with Session(postgres_engine) as session:
        service = _service(session)
        stale, user = service.authenticate(token, now=far_later)
        SqlAlchemyAuthSessionRepository(session).revoke_if_active(stale.id, far_later)
        service.touch(stale, now=far_later + INTERVAL)
        session.commit()
    assert _row(postgres_engine, session_id).last_seen_at == before.last_seen_at


def test_null_last_seen_is_touched(postgres_engine: Engine) -> None:
    _, _, login_name = _seed_local_user(postgres_engine)
    token, session_id = _login(postgres_engine, login_name, P0)
    with Session(postgres_engine) as session, session.begin():
        session.execute(
            update(AuthSessionRecord)
            .where(AuthSessionRecord.id == session_id)
            .values(last_seen_at=None)
        )
    now = datetime.now(UTC)

    assert _touch(postgres_engine, token, session_id, now) == 1
    assert _row(postgres_engine, session_id).last_seen_at == now


def test_authenticated_requests_do_not_write_inside_the_interval(
    postgres_engine: Engine,
) -> None:
    _, _, login_name = _seed_local_user(postgres_engine, must_change_password=False)
    token, session_id = _login(postgres_engine, login_name, P0)
    logged_in_at = _row(postgres_engine, session_id).last_seen_at

    with TestClient(create_app(), base_url="https://testserver") as client:
        client.cookies.set(COOKIE_NAME, token)
        assert client.get("/api/v1/me").status_code == 200
        assert client.get("/api/v1/me").status_code == 200
        assert _row(postgres_engine, session_id).last_seen_at == logged_in_at

        stale = datetime.now(UTC) - INTERVAL * 2
        with Session(postgres_engine) as session, session.begin():
            session.execute(
                update(AuthSessionRecord)
                .where(AuthSessionRecord.id == session_id)
                .values(last_seen_at=stale)
            )
        assert client.get("/api/v1/me").status_code == 200

    refreshed = _row(postgres_engine, session_id).last_seen_at
    assert refreshed is not None and refreshed > stale + INTERVAL
