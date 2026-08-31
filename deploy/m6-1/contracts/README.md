# M6.1 offline recovery contracts

These versioned JSON contracts are the passive boundary for release identity,
the immutable joint recovery set, and each immutable recovery attempt. The
validator in `scripts/m6_1_recovery.py` is intentionally independent of the
EasyAudit application: it imports no product module, database or object-store
SDK, network client, deployment command, or secret resolver.

`manifest_sha256` is computed over the duplicate-free submitted JSON object as
UTF-8 JSON with sorted keys and compact separators, after excluding only the
root document's own hash field. Validators preserve submitted string spellings
(including timestamp offsets), recompute the hash and never trust a submitted
value. Positive fractional RPO/RTO durations are rounded up to the next whole
second, so a boundary exceeded by microseconds cannot be reported as passing.
A recovery set contains only cut-time facts. Both the PostgreSQL backup
completion and the object-root `captured_at` timestamp must be inside the
inclusive joint cut (`cut_started_at` through
`recovery_set_cut_completed`); an independently selected object snapshot is
not valid. Target, timing, readiness and rollback facts belong to the separate
recovery-attempt document. The two documents must reference the same
recovery-set ID and hash. PostgreSQL and object-storage identities are explicit
and must be either immutable OCI digests or immutable managed-service
references.

The recovery attempt records opaque references for the clean target, approved
runtime and approved private network, plus a target fingerprint. The TLS proof
and every exposure probe must carry that same fingerprint and their timestamps
must fall within the inclusive restoration window
(`restoration_started_at` through `restored_ready_at`). Rollback records
distinct known-good (A) and candidate (B) release sets plus failed-target
isolation.

Run the passive checks with:

```text
python scripts/m6_1_recovery.py check-schemas
python scripts/m6_1_recovery.py validate --release release.json \
  --recovery-set recovery-set.json --attempt recovery-attempt.json
```

This slice performs no signing, backup, restore, deployment, network probe or
secret resolution. `detached_signature_ref` is an opaque binding reserved for
the recovery-set signature artifact; creating or verifying that detached
signature, concrete topology and operator evidence remain later M6.1 slices.
Inputs and failures are reported
without echoing document values, untrusted field names, credentials, raw
object keys or customer data. `check-schemas` compares the committed Draft
2020-12 files with the runtime Pydantic schema projection, including nested
constraints; cross-document and time arithmetic remain runtime-only checks.
