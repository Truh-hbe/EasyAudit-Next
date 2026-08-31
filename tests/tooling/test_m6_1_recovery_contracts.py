from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from scripts import m6_1_recovery as recovery

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / ".venv" / "bin" / "python"


def _digest(letter: str) -> str:
    return f"sha256:{letter * 64}"


def _documents() -> tuple[dict, dict, dict]:
    release = {
        "schema_version": "m6.1.release-manifest.v1",
        "release_set_id": "release-1",
        "created_at": "2026-08-31T00:00:00Z",
        "release_digests": {"api": _digest("a"), "web_gateway": _digest("b")},
        "config_revision": "config-1",
        "schema": {"postgres_major": 17, "alembic_head": "alembic-1"},
        "secret_refs": [{"id": "db-secret", "version": "v1"}],
        "manifest_sha256": _digest("0"),
        "signer_key_ref": "signer-1",
    }
    release["manifest_sha256"] = recovery.canonical_hash(
        recovery.ReleaseManifest.model_validate(release)
    )
    recovery_set = {
        "schema_version": "m6.1.recovery-set.v1",
        "recovery_set_id": "recovery-1",
        "release_set_id": "release-1",
        "cut_started_at": "2026-08-31T00:00:00Z",
        "recovery_set_cut_completed": "2026-08-31T00:05:00Z",
        "release_digests": release["release_digests"],
        "config_revision": "config-1",
        "secret_refs": [{"id": "db-secret", "version": "v1"}],
        "postgres_backup": {
            "id": "pg-backup-1",
            "completed_at": "2026-08-31T00:04:00Z",
            "failure_domain_ref": "backup-domain",
        },
        "object_root": {"id": "object-root-1", "count": 2, "content_root": _digest("c")},
        "schema": {"postgres_major": 17, "alembic_head": "alembic-1"},
        "restore_order": ["postgres", "object_fixture", "application", "gateway"],
        "manifest_sha256": _digest("0"),
        "signer_key_ref": "signer-1",
        "primary_failure_domain_ref": "primary-domain",
    }
    recovery_set["manifest_sha256"] = recovery.canonical_hash(
        recovery.RecoverySet.model_validate(recovery_set)
    )
    attempt = {
        "schema_version": "m6.1.recovery-attempt.v1",
        "recovery_attempt_id": "attempt-1",
        "recovery_set_id": "recovery-1",
        "manifest_sha256": recovery_set["manifest_sha256"],
        "target_opaque_id": "target-1",
        "recovery_triggered_at": "2026-08-31T01:05:00Z",
        "restoration_started_at": "2026-08-31T01:06:00Z",
        "restored_ready_at": "2026-08-31T02:05:00Z",
        "observed_rpo_seconds": 3600,
        "observed_rto_seconds": 3600,
        "clock_source": "clock-1",
        "checks": {
            "layered_readiness": True,
            "private_tls": {
                "certificate_fingerprint": _digest("d"),
                "issuer_trust_store_ref": "trust-store-1",
                "hostname_verified": True,
                "validity_checked": True,
                "probe_at": "2026-08-31T02:04:00Z",
            },
            "exposure_probes": [
                {
                    "vantage_class": "approved-private",
                    "target_fingerprint": _digest("e"),
                    "probe_at": "2026-08-31T02:04:00Z",
                    "result": "reachable",
                },
                {
                    "vantage_class": "public-negative",
                    "target_fingerprint": _digest("e"),
                    "probe_at": "2026-08-31T02:04:30Z",
                    "result": "not-reachable",
                    "failure_reason_class": "no-route",
                },
            ],
            "rollback": {
                "known_good_release_set_id": "release-1",
                "failure_injected": "controlled-non-secret",
                "stop_condition": "health-check-failure",
                "database_restored_during_rollback": False,
                "layered_readiness_after_rollback": True,
                "fixture_unchanged": True,
            },
        },
    }
    return release, recovery_set, attempt


def _write_documents(tmp_path: Path, docs: tuple[dict, dict, dict]) -> tuple[Path, Path, Path]:
    paths = tuple(
        tmp_path / name for name in ("release.json", "recovery-set.json", "attempt.json")
    )
    for path, document in zip(paths, docs, strict=True):
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return paths  # type: ignore[return-value]


def test_valid_linked_documents_and_deterministic_hash() -> None:
    release, recovery_set, attempt = _documents()
    assert recovery.validate_documents_from_dicts(release, recovery_set, attempt)
    assert recovery.canonical_hash(recovery.ReleaseManifest.model_validate(release)) == release[
        "manifest_sha256"
    ]


def test_cli_validates_without_mutating_inputs(tmp_path: Path) -> None:
    paths = _write_documents(tmp_path, _documents())
    before = [path.read_bytes() for path in paths]
    result = subprocess.run(
        [
            str(PYTHON),
            str(ROOT / "scripts/m6_1_recovery.py"),
            "validate",
            "--release",
            str(paths[0]),
            "--recovery-set",
            str(paths[1]),
            "--attempt",
            str(paths[2]),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "valid" in result.stdout
    assert [path.read_bytes() for path in paths] == before


@pytest.mark.parametrize(
    ("document", "path", "value"),
    [
        ("release", ("release_digests", "api"), "latest"),
        ("release", ("release_digests", "web_gateway"), _digest("a")),
        ("recovery-set", ("postgres_backup", "failure_domain_ref"), "primary-domain"),
        ("recovery-attempt", ("checks", "rollback", "database_restored_during_rollback"), True),
        ("recovery-attempt", ("checks", "private_tls", "hostname_verified"), False),
    ],
)
def test_no_go_mutations_fail(document: str, path: tuple[str, ...], value: object) -> None:
    release, recovery_set, attempt = _documents()
    selected = {"release": release, "recovery-set": recovery_set, "recovery-attempt": attempt}[
        document
    ]
    mutated = copy.deepcopy(selected)
    cursor: object = mutated
    for key in path[:-1]:
        cursor = cursor[key]  # type: ignore[index]
    cursor[path[-1]] = value  # type: ignore[index]
    if document == "release":
        release = mutated
    elif document == "recovery-set":
        recovery_set = mutated
    else:
        attempt = mutated
    with pytest.raises(ValueError):
        recovery.validate_documents_from_dicts(release, recovery_set, attempt)


def test_attempt_timestamps_are_authoritative() -> None:
    release, recovery_set, attempt = _documents()
    attempt["observed_rto_seconds"] = 1
    with pytest.raises(ValueError, match="timing"):
        recovery.validate_documents_from_dicts(release, recovery_set, attempt)


def test_unknown_post_cut_fields_and_sensitive_values_are_rejected(tmp_path: Path) -> None:
    release, recovery_set, attempt = _documents()
    recovery_set["recovery_triggered_at"] = "2026-08-31T01:00:00Z"
    paths = _write_documents(tmp_path, (release, recovery_set, attempt))
    result = subprocess.run(
        [
            str(PYTHON),
            str(ROOT / "scripts/m6_1_recovery.py"),
            "validate",
            "--release",
            str(paths[0]),
            "--recovery-set",
            str(paths[1]),
            "--attempt",
            str(paths[2]),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "recovery_triggered_at" in result.stderr

    recovery_set.pop("recovery_triggered_at")
    recovery_set["connection_string"] = "postgresql://user:password@example.invalid/db"
    paths = _write_documents(tmp_path, (release, recovery_set, attempt))
    result = subprocess.run(
        [
            str(PYTHON),
            str(ROOT / "scripts/m6_1_recovery.py"),
            "validate",
            "--release",
            str(paths[0]),
            "--recovery-set",
            str(paths[1]),
            "--attempt",
            str(paths[2]),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "password" not in result.stderr
    assert "example.invalid" not in result.stderr


def test_schema_sync_and_ignore_boundaries() -> None:
    recovery.check_schemas(ROOT / "deploy/m6-1/contracts")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for text in (gitignore, dockerignore):
        assert "deploy/private/" in text
        assert "*.key" in text
        assert "*.pem" in text


def test_timezone_aware_timestamps_required() -> None:
    release, recovery_set, attempt = _documents()
    recovery_set["cut_started_at"] = "2026-08-31T00:00:00"
    with pytest.raises(ValueError):
        recovery.validate_documents_from_dicts(release, recovery_set, attempt)
