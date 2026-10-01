"""Cancelling a request must never leave Evidence metadata without its object.

The registration runs in a worker thread that cannot be stopped. Whatever the timing of the
cancellation, the final state is "metadata and object" or "neither"; the only tolerated
leftover is an object without metadata (an orphan for Pilot-4B).
"""

import asyncio
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest

from easyaudit_next.api import review_evidence_uploads as uploads
from easyaudit_next.review_core.domain.models import Evidence
from tests.api.test_evidence_upload_request import PDF, URL, make_client
from tests.evidence_support import FakeEvidenceStore

KEY = "org/o/evidence/k"


def evidence() -> Evidence:
    return Evidence(
        id=uuid4(), organization_id=uuid4(), action_item_id=uuid4(), storage_key=KEY,
        original_name="a.pdf", content_type="application/pdf", size_bytes=1, sha256="0" * 64,
        description=None, uploaded_by=uuid4(), created_at=datetime.now(UTC),
    )  # fmt: skip


class Database:
    """Stand-in for the registration transaction: metadata exists only after 'commit'."""

    def __init__(self) -> None:
        self.metadata = False
        self.at_gate = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def register(
        self, *, fail_before_commit: bool = False, gate: str = "before_commit"
    ) -> Callable[[], Evidence]:
        def run() -> Evidence:
            try:
                if gate == "before_commit":
                    self.at_gate.set()
                    assert self.release.wait(5)
                if fail_before_commit:
                    raise ValueError("Evidence cannot be registered for a cancelled ActionItem")
                if gate == "during_commit":
                    self.at_gate.set()
                    assert self.release.wait(5)
                self.metadata = True  # COMMIT
                return evidence()
            finally:
                self.finished.set()

        return run


def store_with_object() -> FakeEvidenceStore:
    store = FakeEvidenceStore()
    store.objects[KEY] = b"bytes"
    return store


async def cancel_while_gated(db: Database, store: FakeEvidenceStore, register: Any) -> None:
    task = asyncio.ensure_future(uploads._register_and_settle(store, KEY, register))
    await asyncio.to_thread(db.at_gate.wait, 5)
    task.cancel()
    await asyncio.sleep(0.05)  # the request is cancelled; the worker thread is still blocked
    assert not task.done(), "must wait for the registration instead of acting on a guess"
    db.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


def assert_consistent(db: Database, store: FakeEvidenceStore) -> None:
    assert not (db.metadata and KEY not in store.objects), "metadata without an object"


@pytest.mark.parametrize("gate", ["before_commit", "during_commit"])
def test_cancel_then_commit_keeps_the_object(gate: str) -> None:
    db, store = Database(), store_with_object()

    asyncio.run(cancel_while_gated(db, store, db.register(gate=gate)))

    assert db.metadata and KEY in store.objects and store.deleted == []
    assert_consistent(db, store)


def test_cancel_then_rollback_deletes_the_object() -> None:
    db, store = Database(), store_with_object()

    asyncio.run(cancel_while_gated(db, store, db.register(fail_before_commit=True)))

    assert not db.metadata and KEY not in store.objects and store.deleted == [KEY]
    assert_consistent(db, store)


def test_cancel_after_the_commit_keeps_the_object() -> None:
    db, store = Database(), store_with_object()
    db.release.set()

    async def scenario() -> None:
        task = asyncio.ensure_future(
            uploads._register_and_settle(store, KEY, db.register(gate="none"))
        )
        await asyncio.to_thread(db.finished.wait, 5)
        task.cancel()  # the commit is already done; the answer has not been delivered yet
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())

    assert db.metadata and KEY in store.objects and store.deleted == []


def test_commit_with_unknown_outcome_keeps_the_object_and_reraises_the_cause() -> None:
    store = store_with_object()
    cause = RuntimeError("connection lost during COMMIT")

    def register() -> Evidence:
        raise uploads.RegistrationOutcomeUnknown from cause

    with pytest.raises(RuntimeError, match="connection lost"):
        asyncio.run(uploads._register_and_settle(store, KEY, register))

    assert KEY in store.objects and store.deleted == []


def test_cancel_before_the_registration_starts_leaves_neither(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: list[object] = []
    monkeypatch.setattr(uploads, "_preauthorize", lambda *_: None)
    monkeypatch.setattr(uploads, "_register", lambda *a: registered.append(a))

    class BlockedStore(FakeEvidenceStore):
        async def put_stream(self, key: str, chunks: Any) -> Any:
            self.put_calls.append(key)
            await asyncio.Event().wait()  # the upload is still streaming

    store = BlockedStore()

    async def scenario(app: Any) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            request = asyncio.ensure_future(http.post(URL, content=b"data", headers=PDF))
            while not store.put_calls:
                await asyncio.sleep(0.01)
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)

    for client in make_client(store):
        asyncio.run(scenario(client.app))

    assert registered == [] and store.objects == {}
