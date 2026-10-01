"""`easyaudit-next cleanup-auth`: expired throttle windows go, sessions are only counted."""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from easyaudit_next import cli
from easyaudit_next.platform.application.login_throttle import window_start_for
from easyaudit_next.platform.persistence.models import AuthSessionRecord, LoginThrottleRecord
from tests.integration.test_credential_readiness import (
    P0,
    _login,
    _seed_local_user,
)
from tests.integration.test_credential_readiness import postgres_engine as postgres_engine

WINDOW = timedelta(minutes=15)


def test_cleanup_deletes_expired_windows_keeps_current_and_never_touches_sessions(
    postgres_engine: Engine,
) -> None:
    _, _, login_name = _seed_local_user(postgres_engine)
    _, session_id = _login(postgres_engine, login_name, P0)
    now = datetime.now(UTC)
    with Session(postgres_engine) as session, session.begin():
        session.execute(
            update(AuthSessionRecord)
            .where(AuthSessionRecord.id == session_id)
            .values(expires_at=now - timedelta(hours=1))
        )
        before = session.get(AuthSessionRecord, session_id)
        assert before is not None
        snapshot = (before.token_hash, before.expires_at, before.revoked_at, before.last_seen_at)

    current = window_start_for(now, WINDOW)
    keys = {name: sha256(f"{uuid4().hex}-{name}".encode()).hexdigest() for name in ("old", "cur")}
    with Session(postgres_engine) as session, session.begin():
        for name, start in (("old", current - WINDOW), ("cur", current)):
            session.add(
                LoginThrottleRecord(
                    scope="ip",
                    key_hash=keys[name],
                    window_start=start,
                    attempt_count=2,
                    updated_at=now,
                )
            )

    with Session(postgres_engine) as session, session.begin():
        counts = cli.cleanup_auth_in_session(session, window=WINDOW, now=now)

    assert counts["login_throttle_deleted"] >= 1
    assert counts["expired_sessions"] >= 1
    with Session(postgres_engine) as session:
        left = set(
            session.scalars(
                select(LoginThrottleRecord.key_hash).where(
                    LoginThrottleRecord.key_hash.in_(list(keys.values()))
                )
            )
        )
        row = session.get(AuthSessionRecord, session_id)
        assert row is not None  # the session row survives, unchanged
        assert (row.token_hash, row.expires_at, row.revoked_at, row.last_seen_at) == snapshot
    assert left == {keys["cur"]}


def test_command_prints_counts_only(
    postgres_engine: Engine, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["easyaudit-next", "cleanup-auth"])

    cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"event", "login_throttle_deleted", "expired_sessions"}
    assert payload["event"] == "cleanup_auth"
