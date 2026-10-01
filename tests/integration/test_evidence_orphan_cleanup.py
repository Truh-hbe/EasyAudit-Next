"""`cleanup-evidence-orphans` against real PostgreSQL and an in-process S3 server (moto)."""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from easyaudit_next import cli
from easyaudit_next.review_core.application.evidence_maintenance import (
    OrphanCleanupResult,
    cleanup_evidence_orphans,
)
from easyaudit_next.review_core.application.evidence_storage import ListedUpload
from tests.conftest import FakeS3
from tests.integration.evidence_maintenance_support import new_key, put, register_row
from tests.integration.test_credential_readiness import postgres_engine as postgres_engine
from tests.integration.test_evidence_upload_api import SeededCollaboration
from tests.integration.test_evidence_upload_api import seeded as seeded
from tests.unit.test_object_storage import make_store

DAY = timedelta(hours=24)


class ClockedUploads:
    """moto stamps every multipart upload with a fixed date in 2010; report `initiated` instead."""

    def __init__(self, inner: Any, initiated: datetime) -> None:
        self._inner = inner
        self._initiated = initiated

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def list_multipart_uploads(self, prefix: str) -> AsyncIterator[ListedUpload]:
        async for upload in self._inner.list_multipart_uploads(prefix):
            yield replace(upload, initiated=self._initiated)


def run(
    engine: Engine,
    fake: FakeS3,
    *,
    age: timedelta = timedelta(0),
    dry_run: bool = False,
    min_age: timedelta = DAY,
    upload_initiated: datetime | None = None,
    max_delete: int = 100,
    expected_revision: str | None = None,
    scope: Any = None,
) -> OrphanCleanupResult:
    """`age` moves the clock forward, standing in for objects that were written that long ago."""
    store: Any = make_store(fake)
    if upload_initiated is not None:
        store = ClockedUploads(store, upload_initiated)
    return asyncio.run(
        cleanup_evidence_orphans(
            store,
            scope or cli._references_scope(sessionmaker(engine)),
            min_age=min_age,
            now=datetime.now(UTC) + age,
            dry_run=dry_run,
            expected_revision=expected_revision or cli._code_head(),
            max_delete=max_delete,
        )
    )


def test_referenced_objects_stay_young_orphans_stay_old_orphans_go(
    postgres_engine: Engine, seeded: SeededCollaboration, fake_s3: FakeS3
) -> None:
    referenced, orphan = new_key(seeded), new_key(seeded)
    put(fake_s3, referenced, b"kept")
    put(fake_s3, orphan, b"orphan")
    register_row(postgres_engine, seeded, referenced, b"kept")
    for outside in ("misc/notes.txt", f"org/{seeded.organization_id}/other/x"):
        put(fake_s3, outside, b"not evidence")

    young = run(postgres_engine, fake_s3)
    assert (young.scanned, young.orphans, young.kept_young, young.deleted) == (2, 1, 1, 0)
    assert set(fake_s3.keys()) >= {referenced, orphan}

    old = run(postgres_engine, fake_s3, age=2 * DAY)

    assert (old.scanned, old.orphans, old.deleted, old.kept_young) == (2, 1, 1, 0)
    assert set(fake_s3.keys()) == {
        referenced,
        "misc/notes.txt",
        f"org/{seeded.organization_id}/other/x",
    }


def test_a_referenced_object_is_never_deleted_however_old(
    postgres_engine: Engine, seeded: SeededCollaboration, fake_s3: FakeS3
) -> None:
    key = new_key(seeded)
    put(fake_s3, key, b"data")
    register_row(postgres_engine, seeded, key, b"data")

    result = run(postgres_engine, fake_s3, age=3650 * DAY, min_age=timedelta(hours=1))

    assert result.deleted == 0 and result.orphans == 0
    assert fake_s3.keys() == [key]


def test_dry_run_reports_but_deletes_and_aborts_nothing(
    postgres_engine: Engine, seeded: SeededCollaboration, fake_s3: FakeS3
) -> None:
    orphan = new_key(seeded)
    put(fake_s3, orphan, b"orphan")
    fake_s3.client().create_multipart_upload(Bucket=fake_s3.bucket, Key=new_key(seeded))

    result = run(
        postgres_engine, fake_s3, age=2 * DAY, dry_run=True, upload_initiated=datetime.now(UTC)
    )

    assert (result.orphans, result.deleted) == (1, 0)
    assert (result.multipart_stale, result.multipart_aborted) == (1, 0)
    assert fake_s3.keys() == [orphan] and len(fake_s3.open_uploads()) == 1


def test_incomplete_multipart_uploads_older_than_min_age_are_aborted(
    postgres_engine: Engine, seeded: SeededCollaboration, fake_s3: FakeS3
) -> None:
    fake_s3.client().create_multipart_upload(Bucket=fake_s3.bucket, Key=new_key(seeded))
    fake_s3.client().create_multipart_upload(Bucket=fake_s3.bucket, Key="misc/unrelated")

    started = datetime.now(UTC)
    young = run(postgres_engine, fake_s3, upload_initiated=started)
    assert (young.multipart_stale, young.multipart_aborted) == (0, 0)
    assert len(fake_s3.open_uploads()) == 2

    old = run(postgres_engine, fake_s3, age=2 * DAY, upload_initiated=started)

    assert (old.multipart_stale, old.multipart_aborted) == (1, 1)
    [remaining] = fake_s3.client().list_multipart_uploads(Bucket=fake_s3.bucket)["Uploads"]
    assert remaining["Key"] == "misc/unrelated"  # outside the evidence prefix: not ours


def test_cli_prints_one_json_line_and_refuses_a_dangerously_short_min_age(
    postgres_engine: Engine,
    seeded: SeededCollaboration,
    fake_s3: FakeS3,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    put(fake_s3, new_key(seeded), b"orphan")
    monkeypatch.setattr(
        cli, "build_evidence_maintenance_store", lambda _settings: make_store(fake_s3)
    )

    code = cli.cleanup_evidence_orphans_command(timedelta(hours=24), dry_run=True)

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "event": "cleanup_evidence_orphans",
        "dry_run": True,
        "scanned": 1,
        "orphans": 1,
        "deleted": 0,
        "kept_young": 1,
        "multipart_stale": 0,
        "multipart_aborted": 0,
        "skipped_referenced": 0,
        "failed": 0,
        "max_delete": 100,
        "deleted_but_registered": 0,
        "refused": None,
    }
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["cleanup-evidence-orphans", "--min-age-hours", "0"])


def refusal_setup(
    engine: Engine, seeded: SeededCollaboration, fake: FakeS3
) -> tuple[list[str], str]:
    """Old orphans, an old multipart upload, and one referenced object that must survive."""
    kept = new_key(seeded)
    put(fake, kept, b"kept")
    register_row(engine, seeded, kept, b"kept")
    orphans = [new_key(seeded) for _ in range(3)]
    for key in orphans:
        put(fake, key, b"orphan")
    fake.client().create_multipart_upload(Bucket=fake.bucket, Key=new_key(seeded))
    return orphans, kept


def assert_nothing_touched(fake: FakeS3, orphans: list[str], kept: str) -> None:
    assert sorted(fake.keys()) == sorted([kept, *orphans])
    assert len(fake.open_uploads()) == 1  # a refused run aborts nothing either


def test_refuses_to_delete_anything_when_the_database_has_no_evidence_rows(
    postgres_engine: Engine, seeded: SeededCollaboration, fake_s3: FakeS3
) -> None:
    """Wrong or half-restored database. The shared test database always has rows, so the
    reference check is wrapped to report an empty `evidences` table."""
    orphans, kept = refusal_setup(postgres_engine, seeded, fake_s3)
    real = cli._references_scope(sessionmaker(postgres_engine))

    @contextmanager
    def empty_database() -> Iterator[Any]:
        with real() as checker:
            yield SimpleNamespace(
                referenced=lambda keys: set(),  # nothing is referenced in an empty database
                count=lambda: 0,
                alembic_revision=checker.alembic_revision,
            )

    result = run(postgres_engine, fake_s3, age=2 * DAY, scope=empty_database)

    assert result.refused == "no_evidence_rows"
    assert (result.deleted, result.multipart_aborted) == (0, 0)
    assert_nothing_touched(fake_s3, orphans, kept)


def test_refuses_to_delete_anything_when_the_schema_revision_is_not_the_code_head(
    postgres_engine: Engine, seeded: SeededCollaboration, fake_s3: FakeS3
) -> None:
    orphans, kept = refusal_setup(postgres_engine, seeded, fake_s3)

    result = run(postgres_engine, fake_s3, age=2 * DAY, expected_revision="0000_not_the_head")

    assert result.refused == "revision_mismatch"
    assert (result.scanned, result.deleted, result.multipart_aborted) == (0, 0, 0)
    assert_nothing_touched(fake_s3, orphans, kept)


def test_refuses_to_delete_anything_when_more_than_max_delete_are_planned(
    postgres_engine: Engine, seeded: SeededCollaboration, fake_s3: FakeS3
) -> None:
    orphans, kept = refusal_setup(postgres_engine, seeded, fake_s3)

    refused = run(postgres_engine, fake_s3, age=2 * DAY, max_delete=2)

    assert refused.refused == "too_many_deletions"
    assert (refused.orphans, refused.deleted, refused.multipart_aborted) == (3, 0, 0)
    assert_nothing_touched(fake_s3, orphans, kept)

    allowed = run(postgres_engine, fake_s3, age=2 * DAY, max_delete=3)  # the raised limit works

    assert allowed.refused is None and allowed.deleted == 3
    assert fake_s3.keys() == [kept]


def test_a_refusal_is_a_non_zero_exit_with_the_reason_in_the_json(
    postgres_engine: Engine,
    seeded: SeededCollaboration,
    fake_s3: FakeS3,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_code_head", lambda: "0000_not_the_head")
    monkeypatch.setattr(
        cli, "build_evidence_maintenance_store", lambda _settings: make_store(fake_s3)
    )

    code = cli.cleanup_evidence_orphans_command(timedelta(hours=24), dry_run=False)

    assert code == 1
    assert json.loads(capsys.readouterr().out)["refused"] == "revision_mismatch"


def test_more_than_one_listing_page_of_orphans_is_refused_as_a_whole(
    postgres_engine: Engine, seeded: SeededCollaboration, fake_s3: FakeS3
) -> None:
    """The decision is taken on the complete candidate set: 501 objects span two batches, and
    the first batch's 500 must not be deleted before the second one is counted."""
    kept = new_key(seeded)
    put(fake_s3, kept, b"kept")
    register_row(postgres_engine, seeded, kept, b"kept")
    keys = [new_key(seeded) for _ in range(501)]
    for key in keys:
        put(fake_s3, key, b"o")

    refused = run(postgres_engine, fake_s3, age=2 * DAY, max_delete=500)

    assert refused.refused == "too_many_deletions"
    assert (refused.scanned, refused.orphans, refused.deleted) == (502, 501, 0)
    assert len(fake_s3.keys()) == 502

    allowed = run(postgres_engine, fake_s3, age=2 * DAY, max_delete=501)

    assert allowed.refused is None and allowed.deleted == 501
    assert fake_s3.keys() == [kept]


def test_a_deleting_run_needs_a_min_age_of_at_least_24_hours_but_a_dry_run_only_one(
    postgres_engine: Engine,
    seeded: SeededCollaboration,
    fake_s3: FakeS3,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    key = new_key(seeded)
    put(fake_s3, key, b"orphan")
    monkeypatch.setattr(
        cli, "build_evidence_maintenance_store", lambda _settings: make_store(fake_s3)
    )

    refused = cli.cleanup_evidence_orphans_command(timedelta(hours=23), dry_run=False)
    capsys.readouterr()
    dry = cli.cleanup_evidence_orphans_command(timedelta(hours=1), dry_run=True)

    assert refused == 2 and dry == 0
    assert fake_s3.keys() == [key]
