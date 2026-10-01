"""Pilot-3: two real transactions racing on one Idempotency-Key (PostgreSQL arbitrates)."""

import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Barrier, Event
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from easyaudit_next.review_core.application.create_idempotency import CreateIdempotencyService
from tests.integration.create_idempotency_support import (
    CASE_BODY,
    clone,
    count_activities,
    count_cases,
    count_plans,
    count_records,
    login,
    postgres_engine,
    requires_postgres,
    seed_org,
)

pytestmark = requires_postgres
__all__ = ["postgres_engine"]

REPLAYED = "idempotent-replayed"


class _FirstOwnerPause:
    """Hold the transaction that won the claim open until the test releases (or fails) it."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, fail: bool = False) -> None:
        self.claimed = Event()
        self.release = Event()
        self._fail = fail
        original = CreateIdempotencyService.claim

        def claim(service: CreateIdempotencyService, *args: Any, **kwargs: Any) -> Any:
            result = original(service, *args, **kwargs)
            if result is None and not self.claimed.is_set():
                self.claimed.set()
                assert self.release.wait(20)
                if self._fail:
                    raise RuntimeError("injected failure after claim")
            return result

        monkeypatch.setattr(CreateIdempotencyService, "claim", claim)


def _race(
    pool: ThreadPoolExecutor,
    pause: _FirstOwnerPause,
    first: Callable[[], Any],
    second: Callable[[], Any],
) -> tuple[Any, Any]:
    owner: Future[Any] = pool.submit(first)
    assert pause.claimed.wait(20)
    waiter: Future[Any] = pool.submit(second)
    time.sleep(0.5)
    # The second claim waits on the first transaction's uncommitted unique entry.
    assert not waiter.done()
    pause.release.set()
    return owner.result(30), waiter.result(30)


@pytest.mark.parametrize("operation", ["plan", "case"])
def test_concurrent_same_key_same_payload_creates_once(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    organization_id, [(_, name)] = seed_org(postgres_engine)
    client_a = login(postgres_engine, name)
    client_b = clone(client_a)
    headers = {"Idempotency-Key": f"race-{uuid4()}"}
    title = f"{operation}-{uuid4()}"
    path = "/api/v1/review-plans" if operation == "plan" else "/api/v1/review-cases"
    body: dict[str, Any] = {"title": title}
    if operation == "case":
        body.update(CASE_BODY)
    pause = _FirstOwnerPause(monkeypatch)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = _race(
            pool,
            pause,
            lambda: client_a.post(path, json=body, headers=headers),
            lambda: client_b.post(path, json=body, headers=headers),
        )

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert REPLAYED not in first.headers
    assert second.headers[REPLAYED] == "true"
    assert count_records(postgres_engine, organization_id) == 1
    if operation == "plan":
        assert count_plans(postgres_engine, organization_id, title) == 1
        assert count_activities(postgres_engine, organization_id) == 0
    else:
        assert count_cases(postgres_engine, organization_id, title) == 1
        assert count_activities(postgres_engine, organization_id) == 1


@pytest.mark.parametrize("operation", ["plan", "case"])
def test_waiter_creates_after_first_transaction_rolls_back(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    organization_id, [(_, name)] = seed_org(postgres_engine)
    client_a = login(postgres_engine, name)
    client_b = clone(client_a)
    headers = {"Idempotency-Key": f"race-{uuid4()}"}
    title = f"{operation}-{uuid4()}"
    path = "/api/v1/review-plans" if operation == "plan" else "/api/v1/review-cases"
    body: dict[str, Any] = {"title": title}
    if operation == "case":
        body.update(CASE_BODY)
    pause = _FirstOwnerPause(monkeypatch, fail=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = _race(
            pool,
            pause,
            lambda: client_a.post(path, json=body, headers=headers),
            lambda: client_b.post(path, json=body, headers=headers),
        )

    assert first.status_code == 500
    assert second.status_code == 201
    assert REPLAYED not in second.headers  # it created, it did not replay
    assert count_records(postgres_engine, organization_id) == 1
    if operation == "plan":
        assert count_plans(postgres_engine, organization_id, title) == 1
    else:
        assert count_cases(postgres_engine, organization_id, title) == 1
        assert count_activities(postgres_engine, organization_id) == 1


def test_concurrent_creations_with_different_keys_do_not_deadlock(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both transactions hold their claim before either takes the Organization lock.

    This is the interleaving that deadlocks if the claim's foreign keys are checked immediately
    (FOR KEY SHARE on the Organization row, then upgraded to FOR UPDATE by both).
    """

    organization_id, [(_, name)] = seed_org(postgres_engine)
    client_a = login(postgres_engine, name)
    client_b = clone(client_a)
    both_claimed = Barrier(2)
    original = CreateIdempotencyService.claim

    def claim(service: CreateIdempotencyService, *args: Any, **kwargs: Any) -> Any:
        result = original(service, *args, **kwargs)
        both_claimed.wait(20)
        return result

    monkeypatch.setattr(CreateIdempotencyService, "claim", claim)

    def create(client: TestClient, title: str) -> Any:
        return client.post(
            "/api/v1/review-cases",
            json={**CASE_BODY, "title": title},
            headers={"Idempotency-Key": f"k-{uuid4()}"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(create, client_a, f"a-{uuid4()}"),
            pool.submit(create, client_b, f"b-{uuid4()}"),
        ]
        results = [future.result(40) for future in futures]

    assert [r.status_code for r in results] == [201, 201]
    assert count_records(postgres_engine, organization_id) == 2
