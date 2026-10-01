"""`verify-evidence` reads every object back: missing, resized and tampered objects are found."""

import json
from uuid import UUID

import pytest
from sqlalchemy import Engine

from easyaudit_next import cli
from tests.conftest import FakeS3
from tests.integration.evidence_maintenance_support import new_key, put, register_row
from tests.integration.test_credential_readiness import postgres_engine as postgres_engine
from tests.integration.test_evidence_upload_api import SeededCollaboration
from tests.integration.test_evidence_upload_api import seeded as seeded
from tests.unit.test_object_storage import make_store


def verify(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fake: FakeS3,
    organization_id: UUID | None = None,
    limit: int | None = None,
) -> tuple[int, dict[str, object]]:
    monkeypatch.setattr(cli, "build_evidence_maintenance_store", lambda _s: make_store(fake))
    code = cli.verify_evidence_command(organization_id, limit)
    return code, json.loads(capsys.readouterr().out)


def seed_three_problems(
    engine: Engine, seeded: SeededCollaboration, fake: FakeS3
) -> dict[str, UUID]:
    content = b"original bytes 0123456789"
    ids: dict[str, UUID] = {}
    cases = {
        "ok": content,
        "tampered": content,  # same size, one byte different in the bucket
        "resized": content,
        "missing": content,
    }
    for name, data in cases.items():
        key = new_key(seeded)
        record = register_row(engine, seeded, key, data)
        ids[name] = record.id
        if name == "tampered":
            put(fake, key, b"original bytes 012345678X")
        elif name == "resized":
            put(fake, key, content + b"!")
        elif name != "missing":
            put(fake, key, data)
    return ids


def test_intact_evidence_verifies_clean_with_exit_code_zero(
    postgres_engine: Engine,
    seeded: SeededCollaboration,
    fake_s3: FakeS3,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for data in (b"a" * 10, b"b" * 200_000):  # the second spans several download chunks
        key = new_key(seeded)
        put(fake_s3, key, data)
        register_row(postgres_engine, seeded, key, data)

    code, payload = verify(monkeypatch, capsys, fake_s3, seeded.organization_id)

    assert code == 0
    assert payload == {"event": "verify_evidence", "checked": 2, "problems": []}


def test_missing_resized_and_tampered_objects_are_each_reported_with_a_non_zero_exit(
    postgres_engine: Engine,
    seeded: SeededCollaboration,
    fake_s3: FakeS3,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ids = seed_three_problems(postgres_engine, seeded, fake_s3)

    code, payload = verify(monkeypatch, capsys, fake_s3, seeded.organization_id)

    assert code == 1
    assert payload["checked"] == 4
    problems = {item["evidence_id"]: item["problem"] for item in payload["problems"]}  # type: ignore[attr-defined]
    assert problems == {
        str(ids["tampered"]): "sha256_mismatch",
        str(ids["resized"]): "size_mismatch",
        str(ids["missing"]): "missing",
    }


def test_organization_filter_and_limit(
    postgres_engine: Engine,
    seeded: SeededCollaboration,
    fake_s3: FakeS3,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_three_problems(postgres_engine, seeded, fake_s3)

    _, limited = verify(monkeypatch, capsys, fake_s3, seeded.organization_id, limit=2)
    other = verify(monkeypatch, capsys, fake_s3, UUID(int=1))

    assert limited["checked"] == 2
    assert other == (0, {"event": "verify_evidence", "checked": 0, "problems": []})


def test_the_parser_wires_the_command() -> None:
    args = cli.build_parser().parse_args(["verify-evidence", "--limit", "5"])

    assert (args.command, args.limit, args.organization_id) == ("verify-evidence", 5, None)
