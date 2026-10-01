"""A registration that commits after the listing but before the delete must win."""

import asyncio
from collections.abc import Callable
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from easyaudit_next import cli
from easyaudit_next.review_core.application.evidence_maintenance import (
    EvidenceReferences,
    cleanup_evidence_orphans,
)
from tests.conftest import FakeS3
from tests.integration.evidence_maintenance_support import new_key, put, register_row
from tests.integration.test_credential_readiness import postgres_engine as postgres_engine
from tests.integration.test_evidence_upload_api import SeededCollaboration
from tests.integration.test_evidence_upload_api import seeded as seeded
from tests.unit.test_object_storage import make_store


def run_with_hook_after_first_check(
    engine: Engine, fake: FakeS3, hook: Callable[[], None] | None
) -> Any:
    """The first reference check classifies the object as an orphan; `hook` then runs (another
    Session commits), and only after that does the cleanup reach its per-key re-check."""
    real_scope = cli._references_scope(sessionmaker(engine))
    calls = 0

    @contextmanager
    def scope() -> Any:
        nonlocal calls
        calls += 1
        with real_scope() as checker:
            yield checker
        if calls == 1 and hook is not None:
            hook()

    scope_typed: Callable[[], AbstractContextManager[EvidenceReferences]] = scope
    return asyncio.run(
        cleanup_evidence_orphans(
            make_store(fake),
            scope_typed,
            min_age=timedelta(hours=24),
            now=datetime.now(UTC) + timedelta(days=2),
            dry_run=False,
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
