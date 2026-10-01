"""A request that dies on a failed transaction keeps its own error (503), not the touch's 500."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text, update
from sqlalchemy.orm import Session

from easyaudit_next.api.dependencies import AuthenticatedIdentity, DatabaseSession
from easyaudit_next.infrastructure.database import create_database_engine
from easyaudit_next.platform.persistence.models import AuthSessionRecord
from easyaudit_next.platform.settings import Settings
from tests.integration.create_idempotency_support import (
    login,
    postgres_engine,
    requires_postgres,
    seed_org,
)

pytestmark = requires_postgres
__all__ = ["postgres_engine"]


@pytest.fixture
def short_lock_engine() -> Iterator[Engine]:
    engine = create_database_engine(Settings(db_lock_timeout_ms=300, db_statement_timeout_ms=500))
    yield engine
    engine.dispose()


def _make_session_stale(engine: Engine, user_id: object) -> None:
    """last_seen_at far beyond the touch interval: the exit path would issue an UPDATE."""

    with Session(engine) as session, session.begin():
        session.execute(
            update(AuthSessionRecord)
            .where(AuthSessionRecord.user_id == user_id)
            .values(last_seen_at=text("now() - interval '1 day'"))
        )


def test_create_waiting_on_a_held_idempotency_key_is_503_even_when_touch_is_due(
    postgres_engine: Engine, short_lock_engine: Engine
) -> None:
    organization_id, [(user_id, name)] = seed_org(postgres_engine)
    client = login(short_lock_engine, name)
    _make_session_stale(postgres_engine, user_id)
    key = f"held-{uuid4()}"
    with postgres_engine.connect() as holder:
        # Another open transaction owns the key: the claim must wait, then hit lock_timeout.
        holder.execute(
            text(
                "INSERT INTO create_idempotency_records (organization_id, actor_user_id, "
                "operation, idempotency_key, request_fingerprint, review_plan_id, "
                "response_status) VALUES (:o, :u, 'create_review_plan', :k, :f, :p, 201)"
            ),
            {"o": organization_id, "u": user_id, "k": key, "f": "0" * 64, "p": uuid4()},
        )
        response = client.post(
            "/api/v1/review-plans", json={"title": "held"}, headers={"Idempotency-Key": key}
        )
        holder.rollback()

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"


def test_any_request_ending_on_a_failed_transaction_keeps_its_error_mapping(
    postgres_engine: Engine, short_lock_engine: Engine
) -> None:
    _, [(user_id, name)] = seed_org(postgres_engine)
    client = login(short_lock_engine, name)
    _make_session_stale(postgres_engine, user_id)

    @client.app.get("/api/v1/_test/slow")  # type: ignore[union-attr]
    def slow(identity: AuthenticatedIdentity, session: DatabaseSession) -> None:
        session.execute(text("SELECT pg_sleep(5)"))

    response = client.get("/api/v1/_test/slow")

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
