from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import m6_1_recovery as recovery

ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path(sys.executable)


def _digest(letter: str) -> str:
    return f"sha256:{letter * 64}"


def _documents() -> tuple[dict, dict, dict]:
    release = {
        "schema_version": "m6.1.release-manifest.v1",
        "release_set_id": "release-1",
        "created_at": "2026-08-31T00:00:00Z",
        "release_digests": {"api": _digest("a"), "web_gateway": _digest("b")},
        "service_identities": {
            "postgres": {"identity_type": "oci-digest", "reference": _digest("f")},
            "object_storage": {"identity_type": "managed-version", "reference": "s3-v1"},
        },
        "config_revision": "config-1",
        "schema": {"postgres_major": 17, "alembic_head": "alembic-1"},
        "secret_refs": [{"id": "db-secret", "version": "v1"}],
        "manifest_sha256": _digest("0"),
        "signer_key_ref": "signer-1",
    }
    release["manifest_sha256"] = recovery.canonical_hash(release)
    recovery_set = {
        "schema_version": "m6.1.recovery-set.v1",
        "recovery_set_id": "recovery-1",
        "release_set_id": "release-1",
        "cut_started_at": "2026-08-31T00:00:00Z",
        "recovery_set_cut_completed": "2026-08-31T00:05:00Z",
        "release_digests": release["release_digests"],
        "service_identities": release["service_identities"],
        "config_revision": "config-1",
        "secret_refs": [{"id": "db-secret", "version": "v1"}],
        "detached_signature_ref": "signature-1",
        "postgres_backup": {
            "id": "pg-backup-1",
            "completed_at": "2026-08-31T00:04:00Z",
            "failure_domain_ref": "backup-domain",
        },
        "object_root": {
            "id": "object-root-1",
            "count": 2,
            "content_root": _digest("c"),
            "captured_at": "2026-08-31T00:03:00Z",
        },
        "schema": {"postgres_major": 17, "alembic_head": "alembic-1"},
        "restore_order": ["postgres", "object_fixture", "application", "gateway"],
        "manifest_sha256": _digest("0"),
        "signer_key_ref": "signer-1",
        "primary_failure_domain_ref": "primary-domain",
    }
    recovery_set["manifest_sha256"] = recovery.canonical_hash(recovery_set)
    attempt = {
        "schema_version": "m6.1.recovery-attempt.v1",
        "recovery_attempt_id": "attempt-1",
        "recovery_set_id": "recovery-1",
        "manifest_sha256": recovery_set["manifest_sha256"],
        "target_opaque_id": "target-1",
        "target_fingerprint": _digest("e"),
        "clean_target_ref": "target-1",
        "runtime_prerequisite_ref": "runtime-1",
        "private_network_prerequisite_ref": "private-network-1",
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
                "target_fingerprint": _digest("e"),
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
                "candidate_release_set_id": "release-2",
                "failure_injected": "controlled-non-secret",
                "stop_condition": "health-check-failure",
                "database_restored_during_rollback": False,
                "layered_readiness_after_rollback": True,
                "fixture_unchanged": True,
                "failed_target_isolated": True,
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


def _rehash_recovery_set(recovery_set: dict, attempt: dict) -> None:
    recovery_set["manifest_sha256"] = recovery.canonical_hash(recovery_set)
    attempt["manifest_sha256"] = recovery_set["manifest_sha256"]


def test_valid_linked_documents_and_deterministic_hash() -> None:
    release, recovery_set, attempt = _documents()
    attempt["checks"]["exposure_probes"][0]["failure_reason_class"] = None
    assert recovery.validate_documents_from_dicts(release, recovery_set, attempt)
    assert recovery.canonical_hash(recovery.ReleaseManifest.model_validate(release)) == release[
        "manifest_sha256"
    ]


def test_joint_cut_includes_object_root_capture() -> None:
    release, recovery_set, attempt = _documents()
    recovery_set["object_root"]["captured_at"] = "2026-08-30T23:59:59Z"
    _rehash_recovery_set(recovery_set, attempt)
    with pytest.raises(ValueError):
        recovery.validate_documents_from_dicts(release, recovery_set, attempt)

    release, recovery_set, attempt = _documents()
    recovery_set["object_root"]["captured_at"] = "2026-08-31T00:05:00.000001Z"
    _rehash_recovery_set(recovery_set, attempt)
    with pytest.raises(ValueError):
        recovery.validate_documents_from_dicts(release, recovery_set, attempt)

    for captured_at in ("2026-08-31T00:00:00Z", "2026-08-31T00:05:00Z"):
        release, recovery_set, attempt = _documents()
        recovery_set["object_root"]["captured_at"] = captured_at
        _rehash_recovery_set(recovery_set, attempt)
        assert recovery.validate_documents_from_dicts(release, recovery_set, attempt)


def test_readiness_evidence_uses_attempt_target_and_restore_window() -> None:
    release, recovery_set, attempt = _documents()
    attempt["target_fingerprint"] = _digest("f")
    with pytest.raises(ValueError, match="target mismatch"):
        recovery.validate_documents_from_dicts(release, recovery_set, attempt)

    release, recovery_set, attempt = _documents()
    attempt["checks"]["private_tls"]["target_fingerprint"] = _digest("f")
    with pytest.raises(ValueError, match="target mismatch"):
        recovery.validate_documents_from_dicts(release, recovery_set, attempt)

    release, recovery_set, attempt = _documents()
    attempt["checks"]["exposure_probes"][0]["probe_at"] = "2026-08-31T01:05:59Z"
    with pytest.raises(ValueError, match="restoration window"):
        recovery.validate_documents_from_dicts(release, recovery_set, attempt)

    release, recovery_set, attempt = _documents()
    for evidence in [attempt["checks"]["private_tls"], *attempt["checks"]["exposure_probes"]]:
        evidence["probe_at"] = attempt["restoration_started_at"]
    assert recovery.validate_documents_from_dicts(release, recovery_set, attempt)

    release, recovery_set, attempt = _documents()
    for evidence in [attempt["checks"]["private_tls"], *attempt["checks"]["exposure_probes"]]:
        evidence["probe_at"] = attempt["restored_ready_at"]
    assert recovery.validate_documents_from_dicts(release, recovery_set, attempt)


def test_release_component_digests_must_be_distinct_after_rehashing() -> None:
    release, recovery_set, attempt = _documents()
    release["release_digests"]["web_gateway"] = release["release_digests"]["api"]
    release["manifest_sha256"] = recovery.canonical_hash(release)
    recovery_set["release_digests"] = copy.deepcopy(release["release_digests"])
    recovery_set["manifest_sha256"] = recovery.canonical_hash(recovery_set)
    attempt["manifest_sha256"] = recovery_set["manifest_sha256"]
    with pytest.raises(ValueError):
        recovery.validate_documents_from_dicts(release, recovery_set, attempt)


def test_timestamps_require_string_representation() -> None:
    for value in (1_756_549_200, "1756549200"):
        release, recovery_set, attempt = _documents()
        release["created_at"] = value
        with pytest.raises(ValueError, match="invalid document"):
            recovery.validate_documents_from_dicts(release, recovery_set, attempt)

    release, recovery_set, attempt = _documents()
    recovery_set["object_root"]["captured_at"] = 1_756_549_200
    with pytest.raises(ValueError, match="invalid document"):
        recovery.validate_documents_from_dicts(release, recovery_set, attempt)

    release, recovery_set, attempt = _documents()
    attempt["checks"]["private_tls"]["probe_at"] = "1756549200"
    with pytest.raises(ValueError, match="invalid document"):
        recovery.validate_documents_from_dicts(release, recovery_set, attempt)


def test_detached_signature_reference_is_required() -> None:
    release, recovery_set, attempt = _documents()
    recovery_set.pop("detached_signature_ref")
    with pytest.raises(ValueError, match="invalid document"):
        recovery.validate_documents_from_dicts(release, recovery_set, attempt)


def test_timestamp_representation_changes_manifest_hash() -> None:
    release, _, _ = _documents()
    equivalent = copy.deepcopy(release)
    equivalent["created_at"] = "2026-08-31T08:00:00+08:00"
    assert recovery.canonical_hash(equivalent) != recovery.canonical_hash(release)


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


def test_exposure_failure_reason_nullability() -> None:
    release, recovery_set, attempt = _documents()
    attempt["checks"]["exposure_probes"][0]["failure_reason_class"] = None
    assert recovery.validate_documents_from_dicts(release, recovery_set, attempt)

    reachable_reason = copy.deepcopy(attempt)
    reachable_reason["checks"]["exposure_probes"][0]["failure_reason_class"] = "unexpected-reason"
    with pytest.raises(ValueError):
        recovery.validate_documents_from_dicts(release, recovery_set, reachable_reason)

    public_reason = copy.deepcopy(attempt)
    public_reason["checks"]["exposure_probes"][1]["failure_reason_class"] = None
    with pytest.raises(ValueError):
        recovery.validate_documents_from_dicts(release, recovery_set, public_reason)


def test_attempt_timestamps_are_authoritative() -> None:
    release, recovery_set, attempt = _documents()
    attempt["observed_rto_seconds"] = 1
    with pytest.raises(ValueError, match="timing"):
        recovery.validate_documents_from_dicts(release, recovery_set, attempt)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("recovery_triggered_at", "2026-09-01T00:05:00.000001Z", "RPO"),
        ("restored_ready_at", "2026-08-31T05:05:00.000001Z", "RTO"),
    ],
)
def test_fractional_objective_boundaries_round_up(
    field: str, value: str, message: str
) -> None:
    release, recovery_set, attempt = _documents()
    attempt[field] = value
    if field == "recovery_triggered_at":
        attempt["restored_ready_at"] = "2026-09-01T01:05:00.000001Z"
        attempt["observed_rpo_seconds"] = 86_401
        attempt["observed_rto_seconds"] = 3_600
    else:
        attempt["observed_rto_seconds"] = 14_401
    with pytest.raises(ValueError):
        recovery.validate_documents_from_dicts(release, recovery_set, attempt)


def test_duplicate_json_keys_are_rejected_without_echoing_key(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"schema_version":"m6.1.release-manifest.v1",'
        '"release_set_id":"safe","release_set_id":"hostile"}',
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(PYTHON), str(ROOT / "scripts/m6_1_recovery.py"), "hash", "release", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "release_set_id" not in result.stderr
    assert "hostile" not in result.stderr


def _mutate_probe_target(release: dict, recovery_set: dict, attempt: dict) -> None:
    attempt["checks"]["exposure_probes"][1]["target_fingerprint"] = _digest("f")


def _mutate_tls_time(release: dict, recovery_set: dict, attempt: dict) -> None:
    attempt["checks"]["private_tls"]["probe_at"] = "2026-08-31T01:04:59Z"


def _mutate_rollback_candidate(release: dict, recovery_set: dict, attempt: dict) -> None:
    attempt["checks"]["rollback"]["candidate_release_set_id"] = "release-1"


def _mutate_rollback_isolation(release: dict, recovery_set: dict, attempt: dict) -> None:
    attempt["checks"]["rollback"]["failed_target_isolated"] = False


@pytest.mark.parametrize(
    ("mutation", "message", "rehash_recovery"),
    [
        (
            lambda release, recovery_set, attempt: recovery_set["secret_refs"].__setitem__(
                0, {"id": "other-secret", "version": "v1"}
            ),
            "secret reference",
            True,
        ),
        (
            lambda release, recovery_set, attempt: recovery_set["postgres_backup"].__setitem__(
                "completed_at", "2026-08-30T23:59:59Z"
            ),
            "joint cut",
            True,
        ),
        (
            lambda release, recovery_set, attempt: recovery_set["service_identities"][
                "object_storage"
            ].__setitem__("reference", "s3-v2"),
            "service identity",
            True,
        ),
        (
            lambda release, recovery_set, attempt: recovery_set.__setitem__(
                "restore_order", ["postgres", "application", "object_fixture", "gateway"]
            ),
            "restore order",
            True,
        ),
        (
            _mutate_probe_target,
            "one target",
            False,
        ),
        (
            _mutate_tls_time,
            "attempt window",
            False,
        ),
        (
            _mutate_rollback_candidate,
            "candidate",
            False,
        ),
        (
            _mutate_rollback_isolation,
            "rollback",
            False,
        ),
    ],
)
def test_linked_evidence_invariants_are_enforced(
    mutation, message: str, rehash_recovery: bool
) -> None:
    release, recovery_set, attempt = _documents()
    mutation(release, recovery_set, attempt)
    if rehash_recovery:
        _rehash_recovery_set(recovery_set, attempt)
    with pytest.raises(ValueError):
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
    assert "invalid document" in result.stderr

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

    recovery_set.pop("connection_string")
    recovery_set["x_password"] = "-----BEGIN RSA PRIVATE KEY-----super-secret"
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
    assert "x_password" not in result.stderr
    assert "super-secret" not in result.stderr

    hostile_documents = [
        ("AKIA1234567890ABCDEF", "secret-value"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private-key-value"),
        ("hostile_dynamic_key", "dynamic-value"),
    ]
    for hostile_key, hostile_value in hostile_documents:
        release, recovery_set, attempt = _documents()
        release[hostile_key] = hostile_value
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
        assert hostile_key not in result.stdout + result.stderr
        assert hostile_value not in result.stdout + result.stderr


def test_schema_sync_and_ignore_boundaries() -> None:
    recovery.check_schemas(ROOT / "deploy/m6-1/contracts")
    recovery_set_schema = json.loads(
        (ROOT / "deploy/m6-1/contracts/recovery-set.schema.json").read_text(encoding="utf-8")
    )
    assert recovery_set_schema["properties"]["restore_order"]["const"] == [
        "postgres",
        "object_fixture",
        "application",
        "gateway",
    ]
    assert recovery_set_schema["properties"]["service_identities"]["required"] == [
        "postgres",
        "object_storage",
    ]
    attempt_schema = json.loads(
        (ROOT / "deploy/m6-1/contracts/recovery-attempt.schema.json").read_text(encoding="utf-8")
    )
    assert attempt_schema["properties"]["observed_rpo_seconds"]["maximum"] == 86_400
    assert attempt_schema["properties"]["observed_rto_seconds"]["maximum"] == 14_400
    checks = attempt_schema["$defs"]["RecoveryChecks"]
    assert checks["properties"]["layered_readiness"]["const"] is True
    assert checks["properties"]["exposure_probes"]["allOf"]
    reachable_rule = attempt_schema["$defs"]["ExposureProbe"]["allOf"][3]
    assert reachable_rule["then"]["properties"]["failure_reason_class"] == {"type": "null"}
    assert "required" not in reachable_rule["then"]
    assert attempt_schema["$defs"]["TLSProof"]["properties"]["hostname_verified"]["const"] is True
    rollback = attempt_schema["$defs"]["RollbackProof"]["properties"]
    assert rollback["database_restored_during_rollback"]["const"] is False
    assert rollback["failed_target_isolated"]["const"] is True
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
