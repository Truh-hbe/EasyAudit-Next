# M6.1a Recovery Contract / Tooling Acceptance

## 1. Final scope acceptance

M6.1a is accepted for Final Review only when the PR is based on:

```text
main@85aaf364469e57b72a9c340f24d76292054ba5d5
```

and the final `main...HEAD` changed-file set is contained by:

```text
.easyaudit/development-state.json
deploy/m6-1/contracts/**
scripts/m6_1_recovery.py
tests/tooling/test_m6_1_recovery_contracts.py
docs/architecture/m6-1*
docs/architecture/roadmap.md
```

No Review Core, API, migration, frontend, Docker/runtime topology, workflow,
operations-runbook or infrastructure-rehearsal path may be required by this
slice.

The state must identify `M6.1a-recovery-contract-tooling`, remain active, point
to PR #40 and the current work branch, and enter `FINAL_REVIEW` only with an
exact fixed implementation/document candidate plus state-only finalization.

The repository Gate currently names executable source candidates as
`candidate_kind=executable`; M6.1a uses that repository-supported value.

## 2. Static contract acceptance

The following committed schemas must be present and versioned:

```text
deploy/m6-1/contracts/release-manifest.schema.json
deploy/m6-1/contracts/recovery-set.schema.json
deploy/m6-1/contracts/recovery-attempt.schema.json
```

`python scripts/m6_1_recovery.py check-schemas` must prove that the committed
Draft 2020-12 schema files match the runtime Pydantic projection for their
static/nested constraints.

Acceptance includes rejection of at least:

- mutable/missing release component identity;
- missing PostgreSQL/object-storage immutable service identity;
- missing required secret-reference identity/version;
- malformed or timezone-naive timestamps;
- unknown document fields;
- invalid restore-order shape;
- invalid rollback proof shape; and
- malformed target/readiness proof fields.

Passing static schema validation does not assert that any referenced runtime,
network, backup, certificate or restore target exists.

## 3. Canonical hash acceptance

The tooling must recompute the release and recovery-set `manifest_sha256` from
the submitted duplicate-free JSON object, excluding only the root hash field.
It must not trust the supplied hash.

Acceptance requires:

- deterministic hashing for identical submitted JSON values;
- preservation of submitted string spellings when hashing;
- a lexically different timestamp string producing a different hash when the
  submitted document is otherwise identical;
- duplicate JSON keys rejected before hashing;
- release and recovery-set hash mismatch rejected; and
- validation/hash commands not mutating the input files.

## 4. Cross-document and time-window acceptance

The validator must fail closed when the linked documents disagree on release
set, release digests, configuration revision, schema compatibility, service
identity, secret references, recovery-set ID or recovery-set hash.

The recovery set must enforce one inclusive joint-cut window:

```text
cut_started_at
  <= postgres_backup.completed_at
  <= recovery_set_cut_completed

cut_started_at
  <= object_root.captured_at
  <= recovery_set_cut_completed
```

Both exact boundaries are valid; values outside either side are rejected.

The recovery attempt must enforce one target fingerprint across the attempt,
TLS proof and all exposure probes. Probe timestamps must be clipped by
validation to the inclusive evidence window in the sense that evidence outside
this interval is rejected rather than silently accepted:

```text
restoration_started_at <= probe_at <= restored_ready_at
```

M6.1a performs only passive boundary validation. It does not perform the TLS or
exposure probes that would create such evidence.

## 5. RPO/RTO arithmetic acceptance

The attempt's declared timing is not authoritative. The validator recomputes:

```text
observed RPO = recovery_triggered_at - recovery_set_cut_completed
observed RTO = restored_ready_at - recovery_triggered_at
```

The submitted `observed_rpo_seconds` and `observed_rto_seconds` must match the
recomputed values. Positive fractional seconds are rounded up. Negative timing,
RPO greater than 24 hours and RTO greater than 4 hours are rejected by the
contract.

This is **not** real RPO/RTO measurement. It verifies arithmetic and contract
boundaries over submitted synthetic/sanitized timestamps only. Real timing
measurement belongs to M6.1b.

## 6. Sanitization and passive-execution acceptance

The validator must remain offline and side-effect free. It may read only the
supplied local JSON/schema files and must not:

```text
connect to PostgreSQL
connect to object storage
open network connections
resolve secrets
sign or verify detached signatures
build/publish images
deploy services
perform backups or restores
probe TLS/public exposure
mutate submitted evidence
```

Secret-looking values, private-key material, connection strings and hostile
unknown fields must be rejected without echoing sensitive field names or
values in command output.

## 7. Focused tooling tests

`tests/tooling/test_m6_1_recovery_contracts.py` must cover, at minimum:

- valid linked contract documents and deterministic canonical hash;
- joint-cut boundaries for database/object timestamps;
- target fingerprint and restoration-window enforcement;
- distinct required release component digests;
- strict timestamp representation;
- detached-signature reference presence;
- CLI validation without input mutation;
- fail-closed No-Go field mutations;
- authoritative timing recomputation and fractional limit boundaries;
- duplicate JSON-key rejection with leak-safe diagnostics;
- cross-document identity/restore-order invariants;
- sensitive/unknown input rejection;
- committed schema parity; and
- timezone-aware timestamps.

The test suite must not require `.gitignore`, `.dockerignore`, Docker/runtime
artifacts, private-network fixtures or real restore infrastructure; those are
outside the M6.1a allowlist.

## 8. M6.1b authorization boundary

The following are **M6.1b** acceptance evidence and cannot be claimed by
M6.1a:

```text
organization-trusted private HTTPS
approved private/VPN reachability
negative public-exposure proof
real backup failure-domain separation
real PostgreSQL/object recovery cut
real clean-target restore
real layered application/browser readiness
real rollback rehearsal
measured RPO/RTO
```

M6.1b requires its own reviewed Gate and an operator-approved target. No
private-network access, secret resolution, backup/restore action, deployment,
TLS/public probe or rehearsal may begin merely because M6.1a is green. The
operator/human maintainer must explicitly authorize those operations.

## 9. Final Review evidence

Before merge authorization, M6.1a Final Review requires:

1. zero open P0/P1 findings;
2. clean scope proof against the strict M6.1a allowlist;
3. the focused tooling tests passing;
4. a current Review Bundle generated from the exact fixed candidate/control
   relationship; and
5. GitHub Actions green on the exact PR head required by repository policy.

A Final Review pass authorizes only the normal next governance transition. It
does not authorize M6.1b operations, pilot traffic, rollout or merge without
explicit maintainer authorization.
