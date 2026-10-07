"""HTTP surface of transfer-and-reopen (#86 B5) on real PostgreSQL: status mapping,
notification to the new executor, candidate search."""

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from easyaudit_next.api.dependencies import get_current_identity, get_database_session
from easyaudit_next.main import create_app
from easyaudit_next.notifications.persistence import NotificationRecord
from tests.integration.test_review_resource_queries import _actor, _identity
from tests.integration.test_transfer_and_reopen import Seed, postgres_engine  # noqa: F401


def _client(engine: Engine, seed: Seed, user_id: Any) -> Iterator[TestClient]:
    actor = _actor(user_id, seed.organization_id, "Caller")
    app = create_app()

    def database() -> Iterator[Session]:
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    app.dependency_overrides[get_database_session] = database
    app.dependency_overrides[get_current_identity] = lambda: _identity(actor)
    with TestClient(app) as client:
        yield client


def _post(engine: Engine, seed: Seed, caller: Any, **body: Any) -> Any:
    for client in _client(engine, seed, caller):
        return client.post(
            f"/api/v1/action-items/{seed.action_id}/transfer-and-reopen", json=body
        )


def _url(seed: Seed) -> str:
    return f"/api/v1/action-items/{seed.action_id}/transfer-and-reopen"


def test_owner_transfer_returns_the_reopened_action_and_notifies_the_new_executor(
    postgres_engine: Engine,  # noqa: F811
) -> None:
    seed = Seed(postgres_engine)

    response = _post(
        postgres_engine, seed, seed.owner, new_executor_id=str(seed.new1), reason="left"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lifecycle"] == "in_progress"
    assert body["completed_at"] is None
    with Session(postgres_engine) as session:
        recipients = set(
            session.scalars(
                select(NotificationRecord.recipient_user_id).where(
                    NotificationRecord.organization_id == seed.organization_id,
                    NotificationRecord.kind == "action_assignee_added",
                )
            )
        )
    assert recipients == {seed.new1}


@pytest.mark.parametrize(
    ("caller", "body", "status"),
    [
        ("primary", {"reason": "x"}, 403),
        ("admin", {"reason": "x"}, 403),
        ("owner", {"reason": "x", "new_executor_id": "inactive"}, 404),
        ("owner", {"reason": "x", "new_executor_id": "missing"}, 404),
        ("owner", {"reason": "   "}, 422),
        ("owner", {"reason": ""}, 422),
        ("owner", {}, 422),
    ],
)
def test_error_mapping_and_no_side_effects(
    postgres_engine: Engine,  # noqa: F811
    caller: str,
    body: dict[str, Any],
    status: int,
) -> None:
    seed = Seed(postgres_engine)
    seed.set_active(seed.new2, False)
    payload = dict(body)
    if "new_executor_id" not in payload and "reason" in payload:
        payload["new_executor_id"] = str(seed.new1)
    if payload.get("new_executor_id") == "inactive":
        payload["new_executor_id"] = str(seed.new2)
    if payload.get("new_executor_id") == "missing":
        payload["new_executor_id"] = str(uuid4())

    response = _post(postgres_engine, seed, getattr(seed, caller), **payload)

    assert response.status_code == status, response.text
    seed.assert_untouched()


def test_a_transfer_of_an_action_that_is_no_longer_done_is_a_422(
    postgres_engine: Engine,  # noqa: F811
) -> None:
    seed = Seed(postgres_engine, action_lifecycle="in_progress")
    not_done = _post(
        postgres_engine, seed, seed.owner, new_executor_id=str(seed.new1), reason="x"
    )
    assert not_done.status_code == 422

    done = Seed(postgres_engine)
    first = _post(postgres_engine, done, done.owner, new_executor_id=str(done.new1), reason="x")
    assert first.status_code == 200
    # The reopened action is visible before the lock, so this is a 422; the same situation
    # met after waiting on the Case lock is a 409, covered by the race tests.
    second = _post(postgres_engine, done, done.owner, new_executor_id=str(done.new2), reason="y")
    assert second.status_code == 422


def test_candidate_search_is_owner_only_and_only_for_done_actions(
    postgres_engine: Engine,  # noqa: F811
) -> None:
    seed = Seed(postgres_engine)
    url = f"/api/v1/action-items/{seed.action_id}/transfer-candidates"

    for client in _client(postgres_engine, seed, seed.owner):
        response = client.get(url, params={"q": "New"})
    assert response.status_code == 200
    assert {item["display_name"] for item in response.json()} == {"New 1", "New 2"}

    for caller in (seed.primary, seed.admin, seed.lead):
        for client in _client(postgres_engine, seed, caller):
            assert client.get(url, params={"q": "New"}).status_code == 403

    seed.transfer_committed(seed.owner, seed.new1)
    for client in _client(postgres_engine, seed, seed.owner):
        assert client.get(url, params={"q": "New"}).status_code == 422


def test_an_active_executor_is_a_422_for_the_command_and_for_candidate_search(
    postgres_engine: Engine,  # noqa: F811
) -> None:
    seed = Seed(postgres_engine, executors_active=True)

    response = _post(
        postgres_engine, seed, seed.owner, new_executor_id=str(seed.primary), reason="x"
    )
    assert response.status_code == 422
    assert "active executor" in response.json()["detail"]
    for client in _client(postgres_engine, seed, seed.owner):
        candidates = client.get(
            f"/api/v1/action-items/{seed.action_id}/transfer-candidates", params={"q": "New"}
        )
    assert candidates.status_code == 422
    assert seed.action().lifecycle == "done"
    assert seed.transfer_activities() == []
