#!/usr/bin/env python3
"""Backup manifest: build it, and check bundles, live storage and the database against it.

Stdlib only. Used by backup.sh, restore.sh and verify.sh; unit-tested in
tests/unit/test_backup_manifest.py.

  manifest.py build          --dir D --started-at T --images FILE --bucket B \
                             --dump-data FILE     (pg_restore -a -t evidences -t alembic_version)
  manifest.py collect-images --release SHA FILE   (TSV: service, tag, image id, revision label)
  manifest.py verify-bundle  DIR [--fail-degraded]
  manifest.py show-integrity DIR   (print a degraded backup's problem list, exit 0)
  manifest.py verify-live    DIR --lsjson FILE --hashsum FILE --evidences FILE

Exit status is non-zero when anything is inconsistent; every problem is listed on stderr.
`build` exits 3 (EXIT_DEGRADED) after writing a manifest with integrity "degraded": the bundle
is complete as far as the source allowed, but the database references objects that are missing
or differ from their Evidence row.
"""

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FORMAT_VERSION = 1
DUMP_NAME = "database.dump"
OBJECTS_DIR = "objects"
MANIFEST_NAME = "manifest.json"

_ESCAPES = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}
_COPY_HEADER = re.compile(r"^COPY (?P<table>\S+) \((?P<columns>.*)\) FROM stdin;$")


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unescape_copy(value: str) -> str:
    """Undo PostgreSQL COPY text-format escaping for one field."""
    out: list[str] = []
    i = 0
    while i < len(value):
        char = value[i]
        if char != "\\" or i + 1 >= len(value):
            out.append(char)
            i += 1
            continue
        nxt = value[i + 1]
        if nxt in _ESCAPES:
            out.append(_ESCAPES[nxt])
            i += 2
        elif nxt in "01234567":
            j = i + 1
            while j < len(value) and j < i + 4 and value[j] in "01234567":
                j += 1
            out.append(chr(int(value[i + 1 : j], 8)))
            i = j
        elif nxt == "x" and re.match(r"[0-9a-fA-F]{1,2}", value[i + 2 : i + 4]):
            digits = re.match(r"[0-9a-fA-F]{1,2}", value[i + 2 : i + 4])
            assert digits is not None
            out.append(chr(int(digits.group(0), 16)))
            i += 2 + len(digits.group(0))
        else:
            out.append(nxt)
            i += 2
    return "".join(out)


def parse_copy_blocks(text: str) -> dict[str, list[dict[str, str | None]]]:
    """Parse `COPY ... FROM stdin;` blocks of a plain-format pg_restore script into rows."""
    tables: dict[str, list[dict[str, str | None]]] = {}
    columns: list[str] | None = None
    rows: list[dict[str, str | None]] = []
    table = ""
    for line in text.split("\n"):
        if columns is None:
            match = _COPY_HEADER.match(line)
            if match:
                table = match.group("table").split(".")[-1].strip('"')
                columns = [c.strip().strip('"') for c in match.group("columns").split(",")]
                rows = []
            continue
        if line == "\\.":
            tables[table] = rows
            columns = None
            continue
        fields = line.split("\t")
        if len(fields) != len(columns):
            raise ValueError(f"malformed COPY row in table {table}")
        rows.append(
            {
                c: None if f == "\\N" else _unescape_copy(f)
                for c, f in zip(columns, fields, strict=True)
            }
        )
    if columns is not None:
        raise ValueError(f"unterminated COPY block for table {table}")
    return tables


def scan_objects(root: Path) -> list[dict[str, Any]]:
    """Every regular file below `root` as {key, size, sha256}, sorted by key."""
    objects = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        objects.append(
            {
                "key": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return objects


def evidence_problems(
    evidences: Iterable[Mapping[str, Any]], objects: Mapping[str, Mapping[str, Any]]
) -> tuple[list[str], list[str]]:
    """Compare Evidence rows with an object set. Returns (missing keys, mismatches)."""
    missing: list[str] = []
    mismatched: list[str] = []
    for row in evidences:
        key = row["storage_key"]
        obj = objects.get(key)
        if obj is None:
            missing.append(f"evidence {row.get('id')}: object {key!r} not found")
            continue
        if int(row["size_bytes"]) != int(obj["size"]):
            mismatched.append(
                f"evidence {row.get('id')}: size {row['size_bytes']} != {obj['size']} ({key!r})"
            )
        if row["sha256"] != obj["sha256"]:
            mismatched.append(f"evidence {row.get('id')}: sha256 differs from object {key!r}")
    return missing, mismatched


BUILT_SERVICES = ("api", "web", "object-storage")


def images_from_tsv(text: str, expected_release: str) -> tuple[str, dict[str, dict[str, str]]]:
    """Read the running images. The release is the revision label of the api image; every
    self-built image must carry the same one, and it must match the checkout."""
    images: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        service, tag, image_id, revision = (line.split("\t") + [""])[:4]
        images[service] = {"image": tag, "image_id": image_id, "revision": revision}
    for service in BUILT_SERVICES:
        if service not in images:
            raise ValueError(f"service {service!r} is not running")
        if not images[service]["revision"] or images[service]["revision"] == "<no value>":
            raise ValueError(f"{service}: image has no org.opencontainers.image.revision label")
    release = images["api"]["revision"]
    mixed = {s: images[s]["revision"] for s in BUILT_SERVICES if images[s]["revision"] != release}
    if mixed:
        raise ValueError(f"running images come from different releases: api={release}, {mixed}")
    if release != expected_release:
        raise ValueError(
            f"running images are release {release} but EASYAUDIT_RELEASE/checkout is "
            f"{expected_release}; finish the upgrade or set EASYAUDIT_RELEASE={release}"
        )
    return release, images


EXIT_DEGRADED = 3


def build_manifest(
    directory: Path,
    *,
    started_at: datetime,
    finished_at: datetime,
    release_sha: str,
    images: Mapping[str, Any],
    bucket: str,
    dump_data: str,
) -> dict[str, Any]:
    tables = parse_copy_blocks(dump_data)
    revisions = [row["version_num"] for row in tables.get("alembic_version", [])]
    if len(revisions) != 1 or not revisions[0]:
        raise ValueError(f"dump must contain exactly one alembic revision, found {revisions}")
    evidences = tables.get("evidences", [])
    objects = scan_objects(directory / OBJECTS_DIR)
    by_key = {o["key"]: o for o in objects}
    missing, mismatched = evidence_problems(evidences, by_key)
    # Missing or mismatching objects never discard the backup (RPO): it is kept and marked.
    integrity_problems = missing + mismatched
    referenced = {row["storage_key"] for row in evidences}
    dump = directory / DUMP_NAME
    return {
        "format_version": FORMAT_VERSION,
        "backup_timestamp": iso(started_at),
        "backup_finished_at": iso(finished_at),
        "duration_seconds": int((finished_at - started_at).total_seconds()),
        "release_sha": release_sha,
        "alembic_revision": revisions[0],
        "database": {
            "file": DUMP_NAME,
            "size_bytes": dump.stat().st_size,
            "sha256": sha256_file(dump),
        },
        "bucket": bucket,
        "objects": objects,
        "orphan_object_count": len(set(by_key) - referenced),
        "integrity": "degraded" if integrity_problems else "ok",
        "integrity_problems": integrity_problems,
        "images": dict(images),
    }


def load_manifest(directory: Path) -> dict[str, Any]:
    manifest = json.loads((directory / MANIFEST_NAME).read_text())
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"unsupported manifest format {manifest.get('format_version')!r}")
    return dict(manifest)


def verify_bundle(directory: Path, *, fail_degraded: bool = False) -> list[str]:
    """Recompute the dump and every object file and compare them with the manifest.

    A degraded backup is still a consistent bundle; with `fail_degraded` its recorded
    integrity problems are reported as well.
    """
    manifest = load_manifest(directory)
    problems: list[str] = []
    if fail_degraded:
        problems += [f"degraded backup: {p}" for p in manifest.get("integrity_problems", [])]
    dump = directory / manifest["database"]["file"]
    if not dump.is_file():
        problems.append(f"{dump.name}: missing")
    elif sha256_file(dump) != manifest["database"]["sha256"]:
        problems.append(f"{dump.name}: sha256 differs from manifest")
    actual = {o["key"]: o for o in scan_objects(directory / OBJECTS_DIR)}
    expected = {o["key"]: o for o in manifest["objects"]}
    for key in sorted(expected.keys() - actual.keys()):
        problems.append(f"objects/{key}: listed in manifest but missing from bundle")
    for key in sorted(actual.keys() - expected.keys()):
        problems.append(f"objects/{key}: in bundle but not listed in manifest")
    for key in sorted(expected.keys() & actual.keys()):
        if actual[key]["size"] != expected[key]["size"]:
            problems.append(f"objects/{key}: size {actual[key]['size']} != {expected[key]['size']}")
        if actual[key]["sha256"] != expected[key]["sha256"]:
            problems.append(f"objects/{key}: sha256 differs from manifest")
    return problems


def parse_live_objects(lsjson: str, hashsum: str) -> dict[str, dict[str, Any]]:
    """Join `rclone lsjson -R --files-only` and `rclone hashsum sha256 --download` output."""
    sizes = {entry["Path"]: entry["Size"] for entry in json.loads(lsjson)}
    hashes: dict[str, str] = {}
    for line in hashsum.splitlines():
        if line.strip():
            digest, _, path = line.partition("  ")
            hashes[path] = digest.strip()
    return {
        key: {"key": key, "size": size, "sha256": hashes.get(key)} for key, size in sizes.items()
    }


def verify_live(
    manifest: Mapping[str, Any],
    live: Mapping[str, Mapping[str, Any]],
    evidences: Iterable[Mapping[str, Any]],
) -> list[str]:
    """Live bucket vs manifest, and live Evidence rows vs live bucket."""
    problems: list[str] = []
    expected = {o["key"]: o for o in manifest["objects"]}
    for key in sorted(expected.keys() - live.keys()):
        problems.append(f"object {key!r}: in manifest but missing from the bucket")
    for key in sorted(live.keys() - expected.keys()):
        problems.append(f"object {key!r}: in the bucket but not in the manifest")
    for key in sorted(expected.keys() & live.keys()):
        if live[key]["size"] != expected[key]["size"]:
            problems.append(f"object {key!r}: size {live[key]['size']} != {expected[key]['size']}")
        if live[key]["sha256"] != expected[key]["sha256"]:
            problems.append(f"object {key!r}: sha256 differs from manifest")
    missing, mismatched = evidence_problems(evidences, live)
    return problems + missing + mismatched


def _report(problems: list[str]) -> int:
    if problems:
        print(f"INCONSISTENT: {len(problems)} problem(s)", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    return 0


def _print_degraded(problems: list[str]) -> None:
    print("!" * 72, file=sys.stderr)
    print(
        f"DEGRADED BACKUP: {len(problems)} integrity problem(s) in the source data:",
        file=sys.stderr,
    )
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    print("!" * 72, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--dir", type=Path, required=True)
    build.add_argument("--started-at", required=True, help="ISO 8601 UTC")
    build.add_argument("--images", type=Path, required=True, help="collect-images output")
    build.add_argument("--bucket", required=True)
    build.add_argument("--dump-data", type=Path, required=True)
    collect = sub.add_parser("collect-images")
    collect.add_argument("file", type=Path)
    collect.add_argument("--release", required=True)
    bundle = sub.add_parser("verify-bundle")
    bundle.add_argument("dir", type=Path)
    bundle.add_argument("--fail-degraded", action="store_true")
    show = sub.add_parser("show-integrity")
    show.add_argument("dir", type=Path)
    live = sub.add_parser("verify-live")
    live.add_argument("dir", type=Path)
    live.add_argument("--lsjson", type=Path, required=True)
    live.add_argument("--hashsum", type=Path, required=True)
    live.add_argument("--evidences", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "build":
        started = datetime.strptime(args.started_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        collected = json.loads(args.images.read_text())
        manifest = build_manifest(
            args.dir,
            started_at=started,
            finished_at=utc_now(),
            release_sha=collected["release_sha"],
            images=collected["images"],
            bucket=args.bucket,
            dump_data=args.dump_data.read_text(),
        )
        (args.dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n")
        if manifest["integrity"] != "ok":
            _print_degraded(manifest["integrity_problems"])
            return EXIT_DEGRADED
        return 0
    if args.command == "collect-images":
        try:
            release, images = images_from_tsv(args.file.read_text(), args.release)
        except ValueError as exc:
            print(f"BACKUP FAILED: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"release_sha": release, "images": images}))
        return 0
    if args.command == "verify-bundle":
        return _report(verify_bundle(args.dir, fail_degraded=args.fail_degraded))
    if args.command == "show-integrity":
        problems = load_manifest(args.dir).get("integrity_problems", [])
        if problems:
            _print_degraded(problems)
        return 0
    live_objects = parse_live_objects(args.lsjson.read_text(), args.hashsum.read_text())
    evidences = json.loads(args.evidences.read_text() or "[]")
    return _report(verify_live(load_manifest(args.dir), live_objects, evidences))


if __name__ == "__main__":
    sys.exit(main())
