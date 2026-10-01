"""`cleanup-evidence-orphans` against real PostgreSQL and an in-process S3 server (moto)."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
) -> OrphanCleanupResult:
    """`age` moves the clock forward, standing in for objects that were written that long ago."""
    store: Any = make_store(fake)
    if upload_initiated is not None:
        store = ClockedUploads(store, upload_initiated)
    return asyncio.run(
        cleanup_evidence_orphans(
            store,
            cli._references_scope(sessionmaker(engine)),
            min_age=min_age,
            now=datetime.now(UTC) + age,
            dry_run=dry_run,
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
    }
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["cleanup-evidence-orphans", "--min-age-hours", "0"])
