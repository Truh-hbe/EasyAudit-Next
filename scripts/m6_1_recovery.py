#!/usr/bin/env python3
"""Validate the offline M6.1 recovery evidence contract.

This module is deliberately passive.  It reads JSON documents, validates their
shape and cross-document references, and emits only hashes or sanitized error
locations.  It has no product, database, object-storage, network, or process
execution dependency.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = "m6.1.v1"
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
OpaqueId = Annotated[StrictStr, Field(min_length=1, max_length=128, pattern=OPAQUE_ID_RE.pattern)]
Digest = Annotated[StrictStr, Field(pattern=SHA256_RE.pattern)]
Timestamp = datetime
REQUIRED_RESTORE_ORDER = ("postgres", "object_fixture", "application", "gateway")
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


class ContractModel(BaseModel):
    # JSON timestamps arrive as strings; scalar identifiers and booleans use
    # Strict* annotations below so disabling global strict mode does not allow
    # coercion of contract values.
    model_config = ConfigDict(extra="forbid", strict=False, populate_by_name=True)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an explicit offset or Z")
    return value.astimezone(UTC)


class SecretRef(ContractModel):
    id: OpaqueId
    version: OpaqueId


def _require_unique_secret_refs(refs: list[SecretRef]) -> None:
    keys = [(ref.id, ref.version) for ref in refs]
    if len(keys) != len(set(keys)) or len({key[0] for key in keys}) != len(keys):
        raise ValueError("secret references must be unique")


class SchemaCompatibility(ContractModel):
    postgres_major: Literal[17]
    alembic_head: OpaqueId


class PostgresBackup(ContractModel):
    id: OpaqueId
    completed_at: Timestamp
    failure_domain_ref: OpaqueId

    _completed_at_aware = field_validator("completed_at")(_aware)


class OCIServiceIdentity(ContractModel):
    identity_type: Literal["oci-digest"]
    reference: Digest


class ManagedServiceIdentity(ContractModel):
    identity_type: Literal["managed-version"]
    reference: OpaqueId


ServiceIdentity = Annotated[
    OCIServiceIdentity | ManagedServiceIdentity,
    Field(discriminator="identity_type"),
]


class ObjectRoot(ContractModel):
    id: OpaqueId
    count: Annotated[StrictInt, Field(ge=0)]
    content_root: Digest


class TLSProof(ContractModel):
    certificate_fingerprint: Digest
    issuer_trust_store_ref: OpaqueId
    hostname_verified: StrictBool
    validity_checked: StrictBool
    probe_at: Timestamp

    _probe_at_aware = field_validator("probe_at")(_aware)

    @model_validator(mode="after")
    def trusted_tls(self) -> TLSProof:
        if not self.hostname_verified or not self.validity_checked:
            raise ValueError("organization-trusted TLS checks are incomplete")
        return self


class ExposureProbe(ContractModel):
    vantage_class: Literal["approved-private", "public-negative"]
    target_fingerprint: Digest
    probe_at: Timestamp
    result: Literal["reachable", "not-reachable"]
    failure_reason_class: OpaqueId | None = None

    _probe_at_aware = field_validator("probe_at")(_aware)

    @model_validator(mode="after")
    def expected_result(self) -> ExposureProbe:
        if self.vantage_class == "approved-private" and self.result != "reachable":
            raise ValueError("approved-private probe must be reachable")
        if self.vantage_class == "public-negative" and self.result != "not-reachable":
            raise ValueError("public-negative probe must be not-reachable")
        if self.result == "not-reachable" and not self.failure_reason_class:
            raise ValueError("negative probe requires a failure reason class")
        if self.result == "reachable" and self.failure_reason_class is not None:
            raise ValueError("reachable probe must not carry a failure reason")
        return self


class RollbackProof(ContractModel):
    known_good_release_set_id: OpaqueId
    candidate_release_set_id: OpaqueId
    failure_injected: Literal["controlled-non-secret"]
    stop_condition: OpaqueId
    database_restored_during_rollback: StrictBool
    layered_readiness_after_rollback: StrictBool
    fixture_unchanged: StrictBool
    failed_target_isolated: StrictBool

    @model_validator(mode="after")
    def isolated_rollback(self) -> RollbackProof:
        if self.database_restored_during_rollback:
            raise ValueError("rollback must not restore the database")
        if self.candidate_release_set_id == self.known_good_release_set_id:
            raise ValueError("rollback candidate must differ from known-good release")
        if (
            not self.layered_readiness_after_rollback
            or not self.fixture_unchanged
            or not self.failed_target_isolated
        ):
            raise ValueError("rollback readiness and fixture invariants are incomplete")
        return self


class RecoveryChecks(ContractModel):
    layered_readiness: StrictBool
    private_tls: TLSProof
    exposure_probes: list[ExposureProbe] = Field(min_length=2)
    rollback: RollbackProof

    @model_validator(mode="after")
    def complete_probes(self) -> RecoveryChecks:
        classes = {probe.vantage_class for probe in self.exposure_probes}
        if classes != {"approved-private", "public-negative"}:
            raise ValueError("both approved-private and public-negative probes are required")
        if not self.layered_readiness:
            raise ValueError("layered readiness must pass")
        return self


class ReleaseManifest(ContractModel):
    schema_version: Literal["m6.1.release-manifest.v1"]
    release_set_id: OpaqueId
    created_at: Timestamp
    release_digests: dict[StrictStr, Digest]
    service_identities: dict[Literal["postgres", "object_storage"], ServiceIdentity] = Field(
        min_length=2
    )
    config_revision: OpaqueId
    schema_: SchemaCompatibility = Field(alias="schema")
    secret_refs: list[SecretRef] = Field(min_length=1)
    manifest_sha256: Digest
    signer_key_ref: OpaqueId

    _created_at_aware = field_validator("created_at")(_aware)

    @model_validator(mode="after")
    def complete_release_identity(self) -> ReleaseManifest:
        required = {"api", "web_gateway"}
        if not required.issubset(self.release_digests):
            raise ValueError("api and web_gateway image digests are required")
        if set(self.service_identities) != {"postgres", "object_storage"}:
            raise ValueError("postgres and object-storage identities are required")
        _require_unique_secret_refs(self.secret_refs)
        return self


class RecoverySet(ContractModel):
    schema_version: Literal["m6.1.recovery-set.v1"]
    recovery_set_id: OpaqueId
    release_set_id: OpaqueId
    cut_started_at: Timestamp
    recovery_set_cut_completed: Timestamp
    release_digests: dict[StrictStr, Digest]
    service_identities: dict[Literal["postgres", "object_storage"], ServiceIdentity] = Field(
        min_length=2
    )
    config_revision: OpaqueId
    secret_refs: list[SecretRef] = Field(min_length=1)
    postgres_backup: PostgresBackup
    object_root: ObjectRoot
    schema_: SchemaCompatibility = Field(alias="schema")
    restore_order: list[Literal["postgres", "object_fixture", "application", "gateway"]] = Field(
        min_length=4
    )
    manifest_sha256: Digest
    signer_key_ref: OpaqueId
    primary_failure_domain_ref: OpaqueId

    _cut_started_aware = field_validator("cut_started_at")(_aware)
    _cut_completed_aware = field_validator("recovery_set_cut_completed")(_aware)

    @model_validator(mode="after")
    def complete_cut(self) -> RecoverySet:
        if self.recovery_set_cut_completed < self.cut_started_at:
            raise ValueError("recovery set cut completion precedes cut start")
        if not (
            self.cut_started_at
            <= self.postgres_backup.completed_at
            <= self.recovery_set_cut_completed
        ):
            raise ValueError("database backup must complete within the joint cut")
        if self.postgres_backup.failure_domain_ref == self.primary_failure_domain_ref:
            raise ValueError("backup must use a separate failure domain")
        required = {"api", "web_gateway"}
        if not required.issubset(self.release_digests):
            raise ValueError("recovery set must include complete release digests")
        if set(self.service_identities) != {"postgres", "object_storage"}:
            raise ValueError("recovery set must include postgres and object-storage identities")
        if len(set(self.restore_order)) != len(self.restore_order):
            raise ValueError("restore order must not contain duplicates")
        if tuple(self.restore_order) != REQUIRED_RESTORE_ORDER:
            raise ValueError("restore order must be postgres, object_fixture, application, gateway")
        _require_unique_secret_refs(self.secret_refs)
        return self


class RecoveryAttempt(ContractModel):
    schema_version: Literal["m6.1.recovery-attempt.v1"]
    recovery_attempt_id: OpaqueId
    recovery_set_id: OpaqueId
    manifest_sha256: Digest
    target_opaque_id: OpaqueId
    clean_target_ref: OpaqueId
    runtime_prerequisite_ref: OpaqueId
    private_network_prerequisite_ref: OpaqueId
    recovery_triggered_at: Timestamp
    restoration_started_at: Timestamp
    restored_ready_at: Timestamp
    observed_rpo_seconds: Annotated[StrictInt, Field(ge=0, le=86_400)]
    observed_rto_seconds: Annotated[StrictInt, Field(ge=0, le=14_400)]
    clock_source: OpaqueId
    checks: RecoveryChecks

    _triggered_aware = field_validator("recovery_triggered_at")(_aware)
    _started_aware = field_validator("restoration_started_at")(_aware)
    _ready_aware = field_validator("restored_ready_at")(_aware)

    @model_validator(mode="after")
    def ordered_attempt(self) -> RecoveryAttempt:
        if self.restoration_started_at < self.recovery_triggered_at:
            raise ValueError("restore start precedes recovery trigger")
        if self.restored_ready_at < self.restoration_started_at:
            raise ValueError("restored readiness precedes restore start")
        return self


MODELS: dict[str, type[ContractModel]] = {
    "release": ReleaseManifest,
    "recovery-set": RecoverySet,
    "recovery-attempt": RecoveryAttempt,
}
SCHEMA_FILES = {
    "release": "release-manifest.schema.json",
    "recovery-set": "recovery-set.schema.json",
    "recovery-attempt": "recovery-attempt.schema.json",
}
SCHEMA_IDS = {
    "release": "https://easyaudit.invalid/m6.1/release-manifest.schema.json",
    "recovery-set": "https://easyaudit.invalid/m6.1/recovery-set.schema.json",
    "recovery-attempt": "https://easyaudit.invalid/m6.1/recovery-attempt.schema.json",
}

ALLOWED_SECRET_FIELDS = {"secret_refs", "signer_key_ref", "issuer_trust_store_ref"}
FORBIDDEN_FIELD_WORDS = {
    "password",
    "token",
    "private_key",
    "connection_string",
    "access_key",
    "storage_key",
    "credential",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|redis|s3)://"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


class DuplicateKeyError(ValueError):
    """Raised when a JSON object contains duplicate keys."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError("duplicate JSON object key")
        result[key] = value
    return result


def _scan_for_leaks(value: Any, path: tuple[str, ...] = ()) -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if (
                any(word in lowered for word in FORBIDDEN_FIELD_WORDS)
                and key_text not in ALLOWED_SECRET_FIELDS
            ) or any(pattern.search(key_text) for pattern in SECRET_PATTERNS):
                findings.append("forbidden-sensitive-field")
            findings.extend(_scan_for_leaks(child, (*path, key_text)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_scan_for_leaks(child, (*path, str(index))))
    elif isinstance(value, str) and any(pattern.search(value) for pattern in SECRET_PATTERNS):
        findings.append("sensitive-value")
    return findings


def canonical_hash(document: ContractModel | Mapping[str, Any]) -> str:
    """Hash the submitted JSON projection, excluding only its root hash field.

    Callers validating files should pass the duplicate-free raw mapping so that
    timestamp spellings and other submitted string values remain immutable
    evidence. The model form remains supported for tooling callers, but uses
    Pydantic's JSON projection when no raw document is available.
    """
    if isinstance(document, ContractModel):
        data = document.model_dump(mode="json", by_alias=True)
    else:
        data = copy.deepcopy(dict(document))
    data.pop("manifest_sha256", None)
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _ceil_seconds(delta: timedelta) -> int:
    """Return a conservative whole-second duration without float truncation."""
    if delta < timedelta(0):
        return -1
    return delta.days * 86_400 + delta.seconds + (1 if delta.microseconds else 0)


def _load[T: ContractModel](path: Path, kind: str, model_type: type[T]) -> tuple[T, dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except DuplicateKeyError:
        raise ValueError(f"{kind}: unreadable JSON document (DuplicateKeyError)") from None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{kind}: unreadable JSON document ({type(exc).__name__})") from None
    if not isinstance(raw, dict):
        raise ValueError(f"{kind}: document root must be an object")
    leaks = _scan_for_leaks(raw)
    if leaks:
        raise ValueError(f"{kind}: forbidden sensitive material at {leaks[0]}")
    try:
        return model_type.model_validate(raw), raw
    except ValidationError:
        raise ValueError(f"{kind}: invalid document") from None


def validate_documents(
    release_path: Path, recovery_set_path: Path, attempt_path: Path
) -> tuple[ReleaseManifest, RecoverySet, RecoveryAttempt]:
    release, release_raw = _load(release_path, "release", ReleaseManifest)
    recovery_set, recovery_set_raw = _load(recovery_set_path, "recovery-set", RecoverySet)
    attempt, _ = _load(attempt_path, "recovery-attempt", RecoveryAttempt)
    return _validate_linked(release, recovery_set, attempt, release_raw, recovery_set_raw)


def validate_documents_from_dicts(
    release_raw: dict[str, Any], recovery_set_raw: dict[str, Any], attempt_raw: dict[str, Any]
) -> tuple[ReleaseManifest, RecoverySet, RecoveryAttempt]:
    """Validate synthetic documents without touching the filesystem (for tooling tests)."""
    leaks = (
        _scan_for_leaks(release_raw)
        + _scan_for_leaks(recovery_set_raw)
        + _scan_for_leaks(attempt_raw)
    )
    if leaks:
        raise ValueError(f"document: forbidden sensitive material at {leaks[0]}")
    try:
        release = ReleaseManifest.model_validate(release_raw)
        recovery_set = RecoverySet.model_validate(recovery_set_raw)
        attempt = RecoveryAttempt.model_validate(attempt_raw)
    except ValidationError:
        raise ValueError("document: invalid document") from None
    return _validate_linked(release, recovery_set, attempt, release_raw, recovery_set_raw)


def _validate_linked(
    release: ReleaseManifest,
    recovery_set: RecoverySet,
    attempt: RecoveryAttempt,
    release_raw: dict[str, Any],
    recovery_set_raw: dict[str, Any],
) -> tuple[ReleaseManifest, RecoverySet, RecoveryAttempt]:
    if canonical_hash(release_raw) != release.manifest_sha256:
        raise ValueError("release: manifest hash mismatch")
    if canonical_hash(recovery_set_raw) != recovery_set.manifest_sha256:
        raise ValueError("recovery-set: manifest hash mismatch")
    if recovery_set.release_set_id != release.release_set_id:
        raise ValueError("recovery-set: release set reference mismatch")
    if recovery_set.release_digests != release.release_digests:
        raise ValueError("recovery-set: release digest set mismatch")
    if recovery_set.config_revision != release.config_revision:
        raise ValueError("recovery-set: configuration revision mismatch")
    if recovery_set.schema_ != release.schema_:
        raise ValueError("recovery-set: schema compatibility mismatch")
    if recovery_set.service_identities != release.service_identities:
        raise ValueError("recovery-set: service identity set mismatch")
    if {(ref.id, ref.version) for ref in recovery_set.secret_refs} != {
        (ref.id, ref.version) for ref in release.secret_refs
    }:
        raise ValueError("recovery-set: secret reference set mismatch")
    if attempt.recovery_set_id != recovery_set.recovery_set_id:
        raise ValueError("recovery-attempt: recovery set reference mismatch")
    if attempt.manifest_sha256 != recovery_set.manifest_sha256:
        raise ValueError("recovery-attempt: recovery-set manifest hash mismatch")
    rpo_delta = attempt.recovery_triggered_at - recovery_set.recovery_set_cut_completed
    rto_delta = attempt.restored_ready_at - attempt.recovery_triggered_at
    rpo = _ceil_seconds(rpo_delta)
    rto = _ceil_seconds(rto_delta)
    if rpo < 0 or rto < 0:
        raise ValueError("recovery-attempt: timing is negative")
    if attempt.observed_rpo_seconds != rpo or attempt.observed_rto_seconds != rto:
        raise ValueError(
            "recovery-attempt: submitted timing does not match authoritative timestamps"
        )
    if rpo > 24 * 60 * 60:
        raise ValueError("recovery-attempt: observed RPO exceeds 24 hours")
    if rto > 4 * 60 * 60:
        raise ValueError("recovery-attempt: observed RTO exceeds 4 hours")
    if attempt.checks.rollback.known_good_release_set_id != recovery_set.release_set_id:
        raise ValueError("recovery-attempt: rollback baseline does not match release set")
    fingerprints = {probe.target_fingerprint for probe in attempt.checks.exposure_probes}
    if len(fingerprints) != 1:
        raise ValueError("recovery-attempt: exposure probes must identify one target")
    evidence_timestamps = [
        attempt.checks.private_tls.probe_at,
        *(probe.probe_at for probe in attempt.checks.exposure_probes),
    ]
    if any(
        timestamp < attempt.recovery_triggered_at or timestamp > attempt.restored_ready_at
        for timestamp in evidence_timestamps
    ):
        raise ValueError("recovery-attempt: probe evidence is outside the attempt window")
    if attempt.clean_target_ref != attempt.target_opaque_id:
        raise ValueError("recovery-attempt: clean target reference mismatch")
    # Keep the raw parse intentionally used: this guards against callers that
    # bypass Pydantic's strict model and submit a duplicate hash field shape.
    release_fields = set(release.model_dump(mode="json", by_alias=True))
    recovery_set_fields = set(recovery_set.model_dump(mode="json", by_alias=True))
    if set(release_raw) != release_fields or set(recovery_set_raw) != recovery_set_fields:
        raise ValueError("document: field set is not canonical")
    return release, recovery_set, attempt


def _expected_schema(kind: str, model_type: type[ContractModel]) -> dict[str, Any]:
    schema = model_type.model_json_schema(by_alias=True, ref_template="#/$defs/{model}")
    schema["$schema"] = SCHEMA_DIALECT
    schema["$id"] = SCHEMA_IDS[kind]
    fields = {field.alias or name for name, field in model_type.model_fields.items()}
    schema["x-model-fields"] = sorted(fields)

    if kind in {"release", "recovery-set"}:
        digests = schema["properties"]["release_digests"]
        digests["required"] = ["api", "web_gateway"]
        service_identities = schema["properties"]["service_identities"]
        service_identity_refs = [
            {"$ref": "#/$defs/OCIServiceIdentity"},
            {"$ref": "#/$defs/ManagedServiceIdentity"},
        ]
        service_identities.update(
            {
                "additionalProperties": False,
                "required": ["postgres", "object_storage"],
                "properties": {
                    "postgres": {"oneOf": service_identity_refs},
                    "object_storage": {"oneOf": service_identity_refs},
                },
            }
        )
    if kind == "recovery-set":
        schema["properties"]["restore_order"] = {
            "type": "array",
            "const": list(REQUIRED_RESTORE_ORDER),
            "minItems": 4,
            "maxItems": 4,
            "uniqueItems": True,
            "items": {
                "enum": list(REQUIRED_RESTORE_ORDER),
            },
        }
    if kind == "recovery-attempt":
        schema["properties"]["observed_rpo_seconds"]["maximum"] = 86_400
        schema["properties"]["observed_rto_seconds"]["maximum"] = 14_400
        definitions = schema["$defs"]
        definitions["TLSProof"]["properties"]["hostname_verified"]["const"] = True
        definitions["TLSProof"]["properties"]["validity_checked"]["const"] = True
        rollback = definitions["RollbackProof"]["properties"]
        rollback["database_restored_during_rollback"]["const"] = False
        rollback["layered_readiness_after_rollback"]["const"] = True
        rollback["fixture_unchanged"]["const"] = True
        rollback["failed_target_isolated"]["const"] = True
        definitions["RecoveryChecks"]["properties"]["layered_readiness"]["const"] = True

        exposure = definitions["ExposureProbe"]
        exposure["allOf"] = [
            {
                "if": {
                    "properties": {"vantage_class": {"const": "approved-private"}},
                    "required": ["vantage_class"],
                },
                "then": {"properties": {"result": {"const": "reachable"}}},
            },
            {
                "if": {
                    "properties": {"vantage_class": {"const": "public-negative"}},
                    "required": ["vantage_class"],
                },
                "then": {"properties": {"result": {"const": "not-reachable"}}},
            },
            {
                "if": {
                    "properties": {"result": {"const": "not-reachable"}},
                    "required": ["result"],
                },
                "then": {
                    "required": ["failure_reason_class"],
                    "properties": {"failure_reason_class": {"not": {"type": "null"}}},
                },
            },
            {
                "if": {
                    "properties": {"result": {"const": "reachable"}},
                    "required": ["result"],
                },
                "then": {"properties": {"failure_reason_class": {"type": "null"}}},
            },
        ]
        probes = definitions["RecoveryChecks"]["properties"]["exposure_probes"]
        probes["allOf"] = [
            {
                "contains": {
                    "type": "object",
                    "properties": {"vantage_class": {"const": "approved-private"}},
                    "required": ["vantage_class"],
                },
                "minContains": 1,
            },
            {
                "contains": {
                    "type": "object",
                    "properties": {"vantage_class": {"const": "public-negative"}},
                    "required": ["vantage_class"],
                },
                "minContains": 1,
            },
        ]
    return schema


def check_schemas(schema_dir: Path) -> None:
    for kind, model_type in MODELS.items():
        path = schema_dir / SCHEMA_FILES[kind]
        try:
            data = json.loads(
                path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
            )
        except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError):
            raise ValueError(f"schema {kind}: unreadable schema") from None
        if data != _expected_schema(kind, model_type):
            raise ValueError(
                f"schema {kind}: committed schema is out of sync with the runtime model"
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    schemas = sub.add_parser("check-schemas", help="verify committed contract schema metadata")
    schemas.add_argument("--schema-dir", type=Path, default=Path("deploy/m6-1/contracts"))
    hash_parser = sub.add_parser("hash", help="print a canonical manifest hash")
    hash_parser.add_argument("kind", choices=("release", "recovery-set"))
    hash_parser.add_argument("path", type=Path)
    validate = sub.add_parser("validate", help="validate linked release, recovery set and attempt")
    validate.add_argument("--release", required=True, type=Path)
    validate.add_argument("--recovery-set", required=True, type=Path)
    validate.add_argument("--attempt", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "check-schemas":
            check_schemas(args.schema_dir)
            print("M6.1 contract schemas are synchronized")
        elif args.command == "hash":
            _, raw = _load(args.path, args.kind, MODELS[args.kind])
            print(canonical_hash(raw))
        else:
            validate_documents(args.release, args.recovery_set, args.attempt)
            print("M6.1 recovery contract valid")
    except ValueError as exc:
        print(f"contract validation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
