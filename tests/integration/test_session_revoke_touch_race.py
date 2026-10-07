"""Two sessions of one user revoke each other: the exit-path touch must not deadlock them.

Each request UPDATEs the *other* session (revoke) and, when its request scope exits, touches its
*own* session. With a blocking touch the lock order is A->B vs B->A (SQLSTATE 40P01, HTTP 500).
The touch is best effort and skips a row somebody else holds.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text, update
from sqlalchemy.orm import Session

from easyaudit_next.platform.application.authentication import AuthenticationService
from easyaudit_next.platform.domain.ids import AuthSessionId
from easyaudit_next.platform.persistence.models import AuthSessionRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyAuthSessionRepository
from tests.integration.barrier_support import CountingBarrier
from tests.integration.create_idempotency_support import (
    login,
    postgres_engine,
    requires_postgres,
    seed_org,
)

pytestmark = requires_postgres
__all__ = ["postgres_engine"]


def _current_session_id(client: TestClient) -> UUID:
    response = client.get("/api/v1/me/sessions")
    assert response.status_code == 200
    return UUID(next(item["id"] for item in response.json() if item["current"]))


def _make_stale(engine: Engine, *session_ids: UUID) -> None:
    with Session(engine) as session, session.begin():
        session.execute(
            update(AuthSessionRecord)
            .where(AuthSessionRecord.id.in_(session_ids))
            .values(last_seen_at=text("now() - interval '1 hour'"))
        )


def _row(engine: Engine, session_id: UUID) -> AuthSessionRecord:
    with Session(engine) as session:
        return session.execute(
            select(AuthSessionRecord).where(AuthSessionRecord.id == session_id)
        ).scalar_one()


def test_sessions_revoking_each_other_do_not_deadlock(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, [(_, name)] = seed_org(postgres_engine)
    client_a, client_b = login(postgres_engine, name), login(postgres_engine, name)
    id_a, id_b = _current_session_id(client_a), _current_session_id(client_b)
    _make_stale(postgres_engine, id_a, id_b)

    # Both requests hold their revoke UPDATE before either reaches its exit-path touch.
    barrier = CountingBarrier(2)
    original = AuthenticationService.logout

    def logout_then_wait(self: AuthenticationService, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        barrier.wait(timeout=10)

    monkeypatch.setattr(AuthenticationService, "logout", logout_then_wait)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client_a.delete, f"/api/v1/me/sessions/{id_b}")
        second = pool.submit(client_b.delete, f"/api/v1/me/sessions/{id_a}")
        statuses = (first.result(timeout=30).status_code, second.result(timeout=30).status_code)

    assert barrier.hits == 2
    assert statuses == (204, 204)
    assert _row(postgres_engine, id_a).revoked_at is not None
    assert _row(postgres_engine, id_b).revoked_at is not None
    # Revocation sticks: neither token authenticates afterwards.
    assert client_a.get("/api/v1/me/sessions").status_code == 401
    assert client_b.get("/api/v1/me/sessions").status_code == 401


def test_touch_skips_a_session_row_locked_by_another_transaction(
    postgres_engine: Engine,
) -> None:
    _, [(_, name)] = seed_org(postgres_engine)
    client = login(postgres_engine, name)
    session_id = _current_session_id(client)
    _make_stale(postgres_engine, session_id)
    before = _row(postgres_engine, session_id)
    now = datetime.now(UTC)

    with Session(postgres_engine) as holder, holder.begin():
        holder.execute(
            update(AuthSessionRecord)
            .where(AuthSessionRecord.id == session_id)
            .values(last_seen_at=before.last_seen_at)
        )
        with Session(postgres_engine) as toucher, toucher.begin():
            toucher.execute(text("SET LOCAL lock_timeout = '2s'"))
            touched = SqlAlchemyAuthSessionRepository(toucher).touch_if_active(
                AuthSessionId(session_id), before.token_hash, now
            )
        assert touched is None  # skipped immediately, did not wait for the holder

    assert _row(postgres_engine, session_id).last_seen_at == before.last_seen_at
    with Session(postgres_engine) as session, session.begin():
        touched = SqlAlchemyAuthSessionRepository(session).touch_if_active(
            AuthSessionId(session_id), before.token_hash, now
        )
    assert touched is not None
    assert _row(postgres_engine, session_id).last_seen_at == now
