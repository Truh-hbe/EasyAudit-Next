"""Unit tests for deploy/backup/manifest.py (manifest build, bundle/live verification)."""

import hashlib
import importlib.util
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "deploy" / "backup" / "manifest.py"
STARTED = datetime(2026, 9, 30, 2, 0, 0, tzinfo=UTC)
FINISHED = datetime(2026, 9, 30, 2, 0, 42, tzinfo=UTC)
RELEASE = "a" * 40


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("backup_manifest", MANIFEST_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["backup_manifest"] = module
    spec.loader.exec_module(module)
    return module


manifest = _load()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dump_data(revision: str = "20260827_0011", evidences: Sequence[tuple[str, bytes]] = ()) -> str:
    lines = [
        "SET statement_timeout = 0;",
        "COPY public.alembic_version (version_num) FROM stdin;",
        revision,
        "\\.",
        "",
        "COPY public.evidences (id, storage_key, size_bytes, sha256) FROM stdin;",
    ]
    for index, (key, data) in enumerate(evidences):
        lines.append(f"e{index}\t{key}\t{len(data)}\t{_sha(data)}")
    lines.append("\\.")
    return "\n".join(lines) + "\n"


def _bundle(tmp_path: Path, objects: dict[str, bytes]) -> Path:
    (tmp_path / "objects").mkdir()
    (tmp_path / "database.dump").write_bytes(b"PGDMP fake")
    for key, data in objects.items():
        path = tmp_path / "objects" / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return tmp_path


def _build(directory: Path, dump_data: str) -> dict[str, Any]:
    result = manifest.build_manifest(
        directory,
        started_at=STARTED,
        finished_at=FINISHED,
        release_sha=RELEASE,
        images={"api": {"image": f"easyaudit/api:{RELEASE}"}},
        bucket="easyaudit-evidence",
        dump_data=dump_data,
    )
    (directory / "manifest.json").write_text(json.dumps(result))
    assert isinstance(result, dict)
    return result


def test_manifest_records_release_revision_timestamps_and_hashes(tmp_path: Path) -> None:
    objects = {"a/one.txt": b"one", "two.bin": b"\x00\x01"}
    directory = _bundle(tmp_path, objects)
    result = _build(directory, _dump_data(evidences=list(objects.items())))

    assert result["release_sha"] == RELEASE
    assert result["alembic_revision"] == "20260827_0011"
    assert result["backup_timestamp"] == "2026-09-30T02:00:00Z"
    assert result["duration_seconds"] == 42
    assert result["database"]["sha256"] == _sha(b"PGDMP fake")
    assert result["images"]["api"]["image"].endswith(RELEASE)
    assert result["objects"] == [
        {"key": "a/one.txt", "size": 3, "sha256": _sha(b"one")},
        {"key": "two.bin", "size": 2, "sha256": _sha(b"\x00\x01")},
    ]
    assert result["orphan_object_count"] == 0
    assert manifest.verify_bundle(directory) == []


def test_missing_referenced_object_degrades_the_backup_but_keeps_it(tmp_path: Path) -> None:
    directory = _bundle(tmp_path, {"present": b"x"})
    dump = _dump_data(evidences=[("present", b"x"), ("missing/key", b"y")])
    result = _build(directory, dump)
    assert result["integrity"] == "degraded"
    assert any("missing/key" in p for p in result["integrity_problems"])
    assert manifest.verify_bundle(directory) == []  # the bundle itself is consistent
    assert any("missing/key" in p for p in manifest.verify_bundle(directory, fail_degraded=True))


def test_healthy_backup_is_marked_ok(tmp_path: Path) -> None:
    directory = _bundle(tmp_path, {"k": b"v"})
    result = _build(directory, _dump_data(evidences=[("k", b"v")]))
    assert result["integrity"] == "ok" and result["integrity_problems"] == []
    assert manifest.verify_bundle(directory, fail_degraded=True) == []


def test_build_exits_3_for_degraded_and_0_for_ok(tmp_path: Path) -> None:
    def run(name: str, evidences: list[tuple[str, bytes]]) -> int:
        (tmp_path / name).mkdir()
        directory = _bundle(tmp_path / name, {"k": b"v"})
        data = tmp_path / f"{name}.sql"
        data.write_text(_dump_data(evidences=evidences))
        images = tmp_path / f"{name}.json"
        images.write_text(json.dumps({"release_sha": RELEASE, "images": {}}))
        return int(
            manifest.main(
                [
                    "build",
                    "--dir",
                    str(directory),
                    "--started-at",
                    "2026-09-30T02:00:00Z",
                    "--images",
                    str(images),
                    "--bucket",
                    "b",
                    "--dump-data",
                    str(data),
                ]
            )
        )

    assert run("ok", [("k", b"v")]) == 0
    assert run("bad", [("k", b"v"), ("gone", b"g")]) == manifest.EXIT_DEGRADED == 3
    assert json.loads((tmp_path / "bad" / "manifest.json").read_text())["integrity"] == "degraded"


def test_extra_objects_are_orphans_not_failures(tmp_path: Path) -> None:
    directory = _bundle(tmp_path, {"kept": b"k", "orphan": b"o"})
    result = _build(directory, _dump_data(evidences=[("kept", b"k")]))
    assert result["orphan_object_count"] == 1


def test_sha_or_size_mismatch_against_the_database_degrades_the_backup(tmp_path: Path) -> None:
    directory = _bundle(tmp_path, {"k": b"actual"})
    result = _build(directory, _dump_data(evidences=[("k", b"claimed")]))
    assert result["integrity"] == "degraded"
    assert len(result["integrity_problems"]) == 2
    assert any("size" in w for w in result["integrity_problems"])
    assert any("sha256" in w for w in result["integrity_problems"])


def test_dump_without_exactly_one_alembic_revision_is_rejected(tmp_path: Path) -> None:
    directory = _bundle(tmp_path, {})
    with pytest.raises(ValueError, match="alembic"):
        _build(directory, "COPY public.evidences (id) FROM stdin;\n\\.\n")


def test_verify_bundle_reports_every_inconsistency(tmp_path: Path) -> None:
    directory = _bundle(tmp_path, {"a": b"aa", "b": b"bb", "c": b"cc"})
    _build(directory, _dump_data())
    (directory / "objects" / "a").write_bytes(b"AA")  # same size, different content
    (directory / "objects" / "b").write_bytes(b"b")  # different size and content
    (directory / "objects" / "c").unlink()
    (directory / "objects" / "extra").write_bytes(b"?")
    (directory / "database.dump").write_bytes(b"tampered")

    problems = "\n".join(manifest.verify_bundle(directory))
    assert "database.dump: sha256 differs" in problems
    assert "objects/a: sha256 differs" in problems
    assert "objects/b: size" in problems
    assert "objects/c: listed in manifest but missing" in problems
    assert "objects/extra: in bundle but not listed" in problems


def _live(objects: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    lsjson = json.dumps([{"Path": k, "Size": len(v)} for k, v in objects.items()])
    hashsum = "\n".join(f"{_sha(v)}  {k}" for k, v in objects.items())
    return dict(manifest.parse_live_objects(lsjson, hashsum))


def test_verify_live_passes_for_a_faithful_restore(tmp_path: Path) -> None:
    objects = {"dir/a b.txt": b"spaces in key", "z": b""}
    directory = _bundle(tmp_path, objects)
    built = _build(directory, _dump_data(evidences=[("dir/a b.txt", objects["dir/a b.txt"])]))
    evidences = [
        {
            "id": "e0",
            "storage_key": "dir/a b.txt",
            "size_bytes": 13,
            "sha256": _sha(objects["dir/a b.txt"]),
        }
    ]
    assert manifest.verify_live(built, _live(objects), evidences) == []


def test_verify_live_lists_object_and_evidence_problems(tmp_path: Path) -> None:
    objects = {"a": b"aa", "b": b"bb"}
    directory = _bundle(tmp_path, objects)
    built = _build(directory, _dump_data())
    live = _live({"a": b"AA", "stray": b"s"})  # a corrupted, b lost, stray unexpected
    evidences = [
        {"id": "e1", "storage_key": "b", "size_bytes": 2, "sha256": _sha(b"bb")},
        {"id": "e2", "storage_key": "a", "size_bytes": 9, "sha256": _sha(b"aa")},
    ]
    problems = "\n".join(manifest.verify_live(built, live, evidences))
    assert "object 'a': sha256 differs" in problems
    assert "object 'b': in manifest but missing" in problems
    assert "object 'stray': in the bucket but not in the manifest" in problems
    assert "evidence e1: object 'b' not found" in problems
    assert "evidence e2: size 9 != 2" in problems
    assert "evidence e2: sha256 differs" in problems


def test_copy_parser_handles_escapes_and_nulls() -> None:
    text = (
        "COPY public.evidences (id, storage_key, description) FROM stdin;\n"
        "1\ttab\\there\\\\back\\nline\t\\N\n"
        "2\tplain\t\\N\n"
        "\\.\n"
    )
    rows = manifest.parse_copy_blocks(text)["evidences"]
    assert rows[0] == {"id": "1", "storage_key": "tab\there\\back\nline", "description": None}
    assert rows[1]["storage_key"] == "plain"
    with pytest.raises(ValueError, match="unterminated"):
        manifest.parse_copy_blocks("COPY public.t (a) FROM stdin;\nx\n")


def _tsv(**revisions: str) -> str:
    rows = [
        ("gateway", "caddy:2.11.4-alpine", "sha256:g", ""),
        ("web", f"easyaudit/web:{revisions['web']}", "sha256:w", revisions["web"]),
        ("api", f"easyaudit/api:{revisions['api']}", "sha256:a", revisions["api"]),
        ("postgres", "postgres:17.11-alpine3.24", "sha256:p", ""),
        (
            "object-storage",
            f"easyaudit/object-storage:{revisions['storage']}",
            "sha256:o",
            revisions["storage"],
        ),
    ]
    return "\n".join("\t".join(row) for row in rows)


def test_release_comes_from_image_labels_and_must_be_uniform() -> None:
    release, images = manifest.images_from_tsv(
        _tsv(web=RELEASE, api=RELEASE, storage=RELEASE), RELEASE
    )
    assert release == RELEASE
    assert images["gateway"]["image"] == "caddy:2.11.4-alpine"

    with pytest.raises(ValueError, match="different releases"):
        manifest.images_from_tsv(_tsv(web="b" * 40, api=RELEASE, storage=RELEASE), RELEASE)
    with pytest.raises(ValueError, match="EASYAUDIT_RELEASE"):
        manifest.images_from_tsv(_tsv(web=RELEASE, api=RELEASE, storage=RELEASE), "c" * 40)
    with pytest.raises(ValueError, match="no org.opencontainers.image.revision"):
        manifest.images_from_tsv(_tsv(web=RELEASE, api="", storage=RELEASE), RELEASE)


NOW = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)


def _make_backup(root: Path, stamp: str, integrity: str | None, *, partial: bool = False) -> str:
    name = f"easyaudit-backup-{stamp}" + (".partial" if partial else "")
    directory = root / name
    directory.mkdir()
    if integrity is not None:
        (directory / "manifest.json").write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "integrity": integrity,
                    "backup_timestamp": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
                    f"T{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}Z",
                }
            )
        )
    return name


def _expired(root: Path, days: int = 14) -> list[str]:
    return manifest.expired_backups(manifest.list_backups(root), NOW, days)


def test_retention_expires_old_backups_and_keeps_recent_ones(tmp_path: Path) -> None:
    old = _make_backup(tmp_path, "20261001T023000Z", "ok")
    _make_backup(tmp_path, "20261025T023000Z", "ok")
    assert _expired(tmp_path) == [old]


def test_retention_never_deletes_the_newest_ok_backup_even_when_it_is_old(tmp_path: Path) -> None:
    older_ok = _make_backup(tmp_path, "20260901T023000Z", "ok")
    newest_ok = _make_backup(tmp_path, "20260910T023000Z", "ok")
    degraded = [
        _make_backup(tmp_path, "20261001T023000Z", "degraded"),
        _make_backup(tmp_path, "20261020T023000Z", "degraded"),  # inside the window
        _make_backup(tmp_path, "20261029T023000Z", "degraded"),
    ]
    expired = _expired(tmp_path)
    assert newest_ok not in expired
    assert set(expired) == {older_ok, degraded[0]}


def test_retention_treats_unreadable_manifests_as_not_ok(tmp_path: Path) -> None:
    keep = _make_backup(tmp_path, "20260901T023000Z", "ok")
    broken = _make_backup(tmp_path, "20260902T023000Z", None)  # no manifest at all
    assert _expired(tmp_path) == [broken] and keep not in _expired(tmp_path)


def test_retention_cleans_stale_partials_and_ignores_foreign_directories(tmp_path: Path) -> None:
    stale = _make_backup(tmp_path, "20260901T023000Z", None, partial=True)
    fresh = _make_backup(tmp_path, "20261030T110000Z", None, partial=True)
    for foreign in ("lost+found", "easyaudit-backup-old", "easyaudit-backup-2026", "notes"):
        (tmp_path / foreign).mkdir()
    (tmp_path / "easyaudit-backup-20200101T000000Z").write_text("a file, not a directory")
    assert _expired(tmp_path) == [stale]
    assert fresh not in _expired(tmp_path)


def test_partial_backups_never_count_as_the_last_ok_backup(tmp_path: Path) -> None:
    _make_backup(tmp_path, "20260901T023000Z", "ok", partial=True)
    assert manifest.latest_ok(manifest.list_backups(tmp_path)) is None


def _freshness(root: Path, hours: float) -> int:
    return int(manifest._check_freshness(root, hours))


def test_freshness_uses_only_the_newest_integrity_ok_backup(tmp_path: Path) -> None:
    assert _freshness(tmp_path, 24) == 1  # nothing at all
    _make_backup(tmp_path, "20200101T000000Z", "ok")
    assert _freshness(tmp_path, 24) == 1  # ancient
    _make_backup(tmp_path, "20261030T110000Z", "degraded")
    assert _freshness(tmp_path, 24) == 1  # a fresh degraded backup does not help
    _make_backup(tmp_path, "20261030T110000Z", "ok", partial=True)
    assert _freshness(tmp_path, 24) == 1


def test_freshness_passes_for_a_recent_ok_backup_and_fails_past_the_limit(tmp_path: Path) -> None:
    taken = datetime.now(UTC) - timedelta(hours=5)
    _make_backup(tmp_path, taken.strftime(manifest.TIMESTAMP_FORMAT), "ok")
    assert _freshness(tmp_path, 24) == 0
    assert _freshness(tmp_path, 4) == 1
