# M6.1a Recovery Contract / Tooling Validation

## Status and purpose

M6.1a is the offline recovery-contract and tooling slice for EasyAudit-Next.
It is intentionally narrower than the original M6.1 recovery-ready
infrastructure Gate. The branch has been rebased/aligned onto:

```text
main@85aaf364469e57b72a9c340f24d76292054ba5d5
```

The implementation in this slice is passive. It defines versioned recovery
JSON Schemas, a standalone validator and tooling tests that can validate
synthetic or sanitized documents without contacting EasyAudit, PostgreSQL,
object storage, a private network, a TLS endpoint or a secret provider.

M6.1a does not modify Review Core, Scenario policy, product APIs, migrations,
frontend behavior or runtime deployment topology.

## Fixed M6.1a boundary

M6.1a owns only:

```text
release identity contract
joint recovery-set contract
recovery-attempt evidence contract
static JSON Schema parity
canonical SHA-256 recomputation
cross-document linkage checks
joint-cut and restoration-window bounds
authoritative RPO/RTO arithmetic checks
sensitive-value rejection
passive CLI validation
focused tooling tests
```

The committed contract files live under:

```text
deploy/m6-1/contracts/**
```

The passive implementation is:

```text
scripts/m6_1_recovery.py
```

and its focused tests are:

```text
tests/tooling/test_m6_1_recovery_contracts.py
```

No other infrastructure implementation is part of this slice.

## Contract model

M6.1a keeps three immutable document roles separate.

### Release manifest

The release manifest identifies a release set with immutable component/service
identity, configuration revision, expected PostgreSQL/Alembic compatibility,
opaque versioned secret references and a canonical manifest hash. API and
web/gateway digests are required and must be distinct. Service identity must
cover PostgreSQL and object storage using immutable OCI digests or immutable
managed-service references.

The validator never treats mutable tags or secret values as acceptable release
identity.

### Recovery set

The recovery set contains cut-time facts only. It links the release identity to
one joint recovery cut and records:

- `cut_started_at` and `recovery_set_cut_completed`;
- PostgreSQL backup identity/completion and separate failure-domain reference;
- object content-root identity/count/hash and `captured_at`;
- the same release/configuration/schema/service/secret-reference identity;
- the fixed restore-order contract;
- `manifest_sha256`, signer-key reference and detached-signature reference.

Both PostgreSQL backup completion and object-root capture must fall inside the
inclusive joint-cut window. An independently selected object snapshot outside
that cut is rejected by the contract.

M6.1a records only an opaque `detached_signature_ref`; it does not create,
retrieve or cryptographically verify the detached signature artifact.

### Recovery attempt

The attempt document is a proof shape for post-cut facts. It references the
exact recovery-set ID/hash and records an opaque target, one target
fingerprint, declared timing fields, readiness evidence, exposure evidence and
rollback facts.

The validator requires the TLS proof and all exposure probes to repeat the
attempt target fingerprint. Probe timestamps must fall inside the inclusive
`restoration_started_at` through `restored_ready_at` window.

These fields are contract inputs only in M6.1a. Their presence and internal
consistency do not prove that a real network, certificate, restore or rollback
was executed.

## Canonical hashing and passive validation

`manifest_sha256` is recomputed from the submitted duplicate-free JSON object
encoded as UTF-8 JSON with sorted keys and compact separators, excluding only
the root document's own hash field. Submitted string spellings are preserved;
lexically different timestamp representations therefore produce different
hashes even when they describe the same instant.

The validator never trusts a submitted root hash. It recomputes and compares
it. Duplicate JSON keys are rejected before hashing.

Time fields must be RFC 3339 / ISO-8601 strings with an explicit UTC offset or
`Z`. Numeric Unix timestamps and naive timestamps are rejected.

The validator also recomputes:

```text
RPO = recovery_triggered_at - recovery_set_cut_completed
RTO = restored_ready_at - recovery_triggered_at
```

Positive fractional durations are rounded up to whole seconds so a limit
exceeded by microseconds cannot pass due to truncation. M6.1a checks the
arithmetic and declared objective boundaries only; it does not measure a real
environment.

## Schema parity

`check-schemas` compares the committed Draft 2020-12 JSON Schemas with the
runtime Pydantic schema projection, including nested structural constraints.
Cross-document equality, hash recomputation and time arithmetic remain runtime
validator checks because they cannot be fully expressed as isolated document
schemas.

## Safety properties

The validator imports no EasyAudit product module, database driver, object
storage SDK, network client, deployment command or secret resolver. Validation
must not mutate input files.

Unknown fields and secret-looking values are rejected without echoing hostile
field names or values. GitHub/C2C evidence must contain only synthetic or
sanitized opaque references; no credentials, private keys, raw storage keys,
hostnames exposing private topology, customer exports or production data are
required by this slice.

## M6.1b boundary — explicitly not claimed here

Real infrastructure qualification belongs to **M6.1b** and requires explicit
operator authorization before any action that can touch a real environment.
M6.1a therefore does not claim or authorize:

```text
real private/VPN network access
organization-trusted TLS validation
negative public-exposure probing
real PostgreSQL backup or restore
real object-store snapshot or restore
real failure-domain qualification
clean-target deployment or restore rehearsal
real rollback rehearsal
measured environment RPO/RTO
secret resolution
image publication or deployment
pilot traffic
```

M6.1b may consume the contracts frozen by M6.1a, but it must have its own
reviewed Gate, operator-approved target, sanitized evidence plan and explicit
human authorization. A passing M6.1a CI run is necessary tooling evidence, not
disaster-recovery qualification.

M6-RC remains responsible for final joint recovery qualification of the actual
rollout release after later M6 application/schema/Evidence changes.

## Machine scope

The active M6.1a allowlist is strictly:

```text
.easyaudit/development-state.json
deploy/m6-1/contracts/**
scripts/m6_1_recovery.py
tests/tooling/test_m6_1_recovery_contracts.py
docs/architecture/m6-1*
docs/architecture/roadmap.md
```

In particular, runtime deployment files, Docker ignore policy, workflow files,
operations runbooks, product source, migrations, browser/API tests and
infrastructure-rehearsal tests are outside M6.1a.

## Final Review entry

M6.1a may enter `FINAL_REVIEW` only after the aligned implementation/doc
candidate is fixed to an exact commit and any later control commit changes only
`.easyaudit/development-state.json`. Final Review evaluates the passive
contracts/tooling and exact-head CI; it does not authorize M6.1b operations or
merge without the normal independent review and explicit maintainer decision.
