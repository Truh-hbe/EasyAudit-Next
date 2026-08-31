# M6.1 offline recovery contracts

These versioned JSON contracts are the passive boundary for release identity,
the immutable joint recovery set, and each immutable recovery attempt. The
validator in `scripts/m6_1_recovery.py` is intentionally independent of the
EasyAudit application: it imports no product module, database or object-store
SDK, network client, deployment command, or secret resolver.

`manifest_sha256` is computed over UTF-8 JSON with sorted keys and compact
separators after excluding only the manifest's own hash field. Validators
recompute it and never trust a submitted value. A recovery set contains only
cut-time facts; target, timing, readiness and rollback facts belong to the
separate recovery-attempt document. The two documents must reference the same
recovery-set ID and hash.

Run the passive checks with:

```text
python scripts/m6_1_recovery.py check-schemas
python scripts/m6_1_recovery.py validate --release release.json \
  --recovery-set recovery-set.json --attempt recovery-attempt.json
```

This slice performs no signing, backup, restore, deployment, network probe or
secret resolution. Detached signature verification, concrete topology and
operator evidence remain later M6.1 slices. Inputs and failures are reported
without echoing document values, credentials, raw object keys or customer data.
