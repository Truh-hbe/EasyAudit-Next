"""A registration that commits after the listing but before the delete must win."""

import asyncio
import json
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from easyaudit_next import cli
from easyaudit_next.review_core.application.evidence_maintenance import (
    EvidenceReferences,
    cleanup_evidence_orphans,
)
from easyaudit_next.review_core.application.evidence_storage import ObjectStoreError
from tests.conftest import FakeS3
from tests.integration.evidence_maintenance_support import new_key, put, register_row
from tests.integration.test_credential_readiness import postgres_engine as postgres_engine
from tests.integration.test_evidence_upload_api import SeededCollaboration
from tests.integration.test_evidence_upload_api import seeded as seeded
from tests.unit.test_object_storage import make_store


def run_with_hook_after_first_check(
    engine: Engine, fake: FakeS3, hook: Callable[[], None] | None
) -> Any:
    """The object is classified as an orphan and the guards pass; `hook` then runs (another
    Session commits), and only after that does the cleanup reach its per-key re-check."""
    real_scope = cli._references_scope(sessionmaker(engine))
    calls = 0

    @contextmanager
    def scope() -> Any:
        nonlocal calls
        calls += 1
        with real_scope() as checker:
            yield checker
        if calls == 3 and hook is not None:  # 1 revision, 2 classify, 3 guards; 4 is the re-check
            hook()

    scope_typed: Callable[[], AbstractContextManager[EvidenceReferences]] = scope
    return asyncio.run(
        cleanup_evidence_orphans(
            make_store(fake),
            scope_typed,
            min_age=timedelta(hours=24),
            now=datetime.now(UTC) + timedelta(days=2),
            dry_run=False,
            expected_revision=cli._code_head(),
            max_delete=100,
        )
    )


def test_registration_committed_between_listing_and_delete_keeps_the_object(
    postgres_engine: Engine, seeded: SeededCollaboration, fake_s3: FakeS3
) -> None:
    key = new_key(seeded)
    put(fake_s3, key, b"late registration")

    result = run_with_hook_after_first_check(
        postgres_engine,
        fake_s3,
        lambda: register_row(postgres_engine, seeded, key, b"late registration"),
    )

    assert fake_s3.keys() == [key]  # still there
    assert (result.orphans, result.deleted, result.skipped_referenced) == (1, 0, 1)


def test_control_without_the_late_registration_the_same_object_is_deleted(
    postgres_engine: Engine, seeded: SeededCollaboration, fake_s3: FakeS3
) -> None:
    put(fake_s3, new_key(seeded), b"real orphan")

    result = run_with_hook_after_first_check(postgres_engine, fake_s3, None)

    assert fake_s3.keys() == []
    assert (result.orphans, result.deleted, result.skipped_referenced) == (1, 1, 0)


class RegistrationBeforeDelete:
    """The worst timing: the per-key re-check has passed, and a registration commits just
    before the object is deleted."""

    def __init__(self, inner: Any, hook: Callable[[str], None]) -> None:
        self._inner = inner
        self._hook = hook

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def delete(self, key: str) -> None:
        self._hook(key)
        await self._inner.delete(key)


def test_a_registration_after_the_final_recheck_is_detected_reported_and_fails_the_run(
    postgres_engine: Engine,
    seeded: SeededCollaboration,
    fake_s3: FakeS3,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The accepted window (pilot): this does NOT show the object survives. It shows the loss
    is caught: ERROR log, a count in the JSON, a non-zero exit."""
    key = new_key(seeded)
    put(fake_s3, key, b"late registration")
    store = RegistrationBeforeDelete(
        make_store(fake_s3),
        lambda _key: register_row(postgres_engine, seeded, key, b"late registration"),
    )
    monkeypatch.setattr(cli, "build_evidence_maintenance_store", lambda _settings: store)
    real = cli.cleanup_evidence_orphans

    async def two_days_later(*args: Any, **kwargs: Any) -> Any:
        return await real(*args, **{**kwargs, "now": datetime.now(UTC) + timedelta(days=2)})

    monkeypatch.setattr(cli, "cleanup_evidence_orphans", two_days_later)

    with caplog.at_level(logging.ERROR, logger="easyaudit.app"):
        code = cli.cleanup_evidence_orphans_command(timedelta(hours=24), dry_run=False)

    assert fake_s3.keys() == []  # the object is gone: the window is real
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert (payload["deleted"], payload["deleted_but_registered"]) == (1, 1)
    [record] = [
        r for r in caplog.records if r.getMessage() == "evidence_object_deleted_while_registered"
    ]
    assert record.levelno == logging.ERROR
    assert set(record.fields) == {"storage_key", "evidence_id"}  # type: ignore[attr-defined]
    assert record.fields["storage_key"] == key  # type: ignore[attr-defined]


def clock_two_days_ahead(monkeypatch: pytest.MonkeyPatch) -> None:
    real = cli.cleanup_evidence_orphans

    async def two_days_later(*args: Any, **kwargs: Any) -> Any:
        return await real(*args, **{**kwargs, "now": datetime.now(UTC) + timedelta(days=2)})

    monkeypatch.setattr(cli, "cleanup_evidence_orphans", two_days_later)


def test_an_incident_is_logged_and_counted_even_if_a_later_step_fails(
    postgres_engine: Engine,
    seeded: SeededCollaboration,
    fake_s3: FakeS3,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    keys = [new_key(seeded), new_key(seeded)]
    for key in keys:
        put(fake_s3, key, b"data")
    registered: list[str] = []

    def register_first_deleted_key(key: str) -> None:
        if not registered:  # a late registration for whichever object is deleted first
            registered.append(key)
            register_row(postgres_engine, seeded, key, b"data")

    store = RegistrationBeforeDelete(make_store(fake_s3), register_first_deleted_key)
    monkeypatch.setattr(cli, "build_evidence_maintenance_store", lambda _settings: store)
    real_scope = cli._references_scope(sessionmaker(postgres_engine))
    calls = 0

    @contextmanager
    def failing_later() -> Any:
        nonlocal calls
        calls += 1
        if calls == 6:  # 1 revision, 2 classify, 3 guard, 4 re-check, 5 post-check, 6 next re-check
            raise RuntimeError("database went away")
        with real_scope() as checker:
            yield checker

    monkeypatch.setattr(cli, "_references_scope", lambda _factory: failing_later)
    clock_two_days_ahead(monkeypatch)

    with caplog.at_level(logging.ERROR, logger="easyaudit.app"):
        code = cli.cleanup_evidence_orphans_command(timedelta(hours=24), dry_run=False)

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "RuntimeError"  # the type only
    assert (payload["deleted"], payload["deleted_but_registered"]) == (1, 1)
    [record] = [
        r for r in caplog.records if r.getMessage() == "evidence_object_deleted_while_registered"
    ]
    assert record.fields["storage_key"] == registered[0]  # type: ignore[attr-defined]


def test_a_delete_that_errors_but_removed_the_object_of_a_registered_key_is_an_incident(
    postgres_engine: Engine, seeded: SeededCollaboration, fake_s3: FakeS3
) -> None:
    key = new_key(seeded)
    put(fake_s3, key, b"data")
    inner = make_store(fake_s3)

    class ErrorsAfterDeleting:
        def __getattr__(self, name: str) -> Any:
            return getattr(inner, name)

        async def delete(self, key: str) -> None:
            register_row(postgres_engine, seeded, key, b"data")
            await inner.delete(key)
            raise ObjectStoreError("response lost")  # the delete happened; the caller can't know

    incidents: list[Any] = []
    result = asyncio.run(
        cleanup_evidence_orphans(
            ErrorsAfterDeleting(),  # type: ignore[arg-type]
            cli._references_scope(sessionmaker(postgres_engine)),
            min_age=timedelta(hours=24),
            now=datetime.now(UTC) + timedelta(days=2),
            dry_run=False,
            expected_revision=cli._code_head(),
            max_delete=100,
            on_incident=incidents.append,
        )
    )

    assert fake_s3.keys() == []
    assert (result.failed, result.deleted, result.deleted_but_registered) == (1, 0, 1)
    assert [i.storage_key for i in incidents] == [key]


def test_a_delete_that_errors_and_left_the_object_in_place_is_not_an_incident(
    postgres_engine: Engine, seeded: SeededCollaboration, fake_s3: FakeS3
) -> None:
    key = new_key(seeded)
    put(fake_s3, key, b"data")
    inner = make_store(fake_s3)

    class FailsBeforeDeleting:
        def __getattr__(self, name: str) -> Any:
            return getattr(inner, name)

        async def delete(self, key: str) -> None:
            register_row(postgres_engine, seeded, key, b"data")
            raise ObjectStoreError("refused")

    result = asyncio.run(
        cleanup_evidence_orphans(
            FailsBeforeDeleting(),  # type: ignore[arg-type]
            cli._references_scope(sessionmaker(postgres_engine)),
            min_age=timedelta(hours=24),
            now=datetime.now(UTC) + timedelta(days=2),
            dry_run=False,
            expected_revision=cli._code_head(),
            max_delete=100,
        )
    )

    assert fake_s3.keys() == [key]
    assert (result.failed, result.deleted_but_registered) == (1, 0)
