# M6.1 Recovery-Ready Infrastructure Acceptance

## 1. Gate and scope acceptance

The M6.1 candidate is acceptable for independent Gate Review only when:

1. the candidate base is exactly
   `main@43fdf9d9a98c3e01d4f2fd50d795567c2fe9a62c`;
2. the initial candidate changes only the development state, roadmap and the
   two M6.1 Gate documents;
3. the state is `active=true`, `milestone=M6`,
   `slice=M6.1-recovery-ready-infrastructure`,
   `phase=GATE_DRAFT`, `candidate_kind=executable`, with empty `fixed_head`
   and `docs_review_head`;
4. the state records the exact work branch, the two Gate documents and the
   narrow prospective implementation allowlist;
5. the Gate check, JSON validation, `git diff --check` and a clean Review
   Bundle pass; and
6. no deployment resource, image, secret, traffic, restore rehearsal,
   migration, product source or business behavior is changed.

This Gate Draft review may authorize only `GATE_DRAFT -> GATE_REVIEW`.
`GATE_REVIEW` requires a separate re-review; only its passing result may
authorize `GATE_REVIEW -> IMPLEMENTATION`. While that re-review is pending,
deployment, image publication, secret access, restore rehearsal and traffic
remain forbidden. Neither Gate review authorizes real traffic.

## 2. Topology and trust-boundary acceptance

Implementation must provide evidence for a fresh disposable deployment with:

- HTTPS web gateway as the only host-published component;
- TCP 443 bound only to an explicitly supplied approved private/VPN address;
- no published API, PostgreSQL, object API or administration-console port;
- built React product and relative `/api/v1/*` proxy through one origin;
- organization-trusted certificate chain from the approved network; and
- a negative public-exposure check that is independent of repository review.

Vite development TLS, `ignoreHTTPSErrors`, a self-signed certificate or a
successful request from an unapproved public route cannot satisfy this Gate.
The existing development `compose.yaml` is not an acceptable pilot artifact.

## 3. Release, secret and backup acceptance

Static validators and implementation evidence must reject:

- mutable image tags or a missing API/web-gateway artifact digest;
- wildcard or public host bindings;
- published internal service ports;
- default credentials or secret-looking values;
- missing secret-reference identifiers or versions;
- credentials, private keys, raw object keys or secret values in Git, image
  layers, logs, bundles or sanitized evidence;
- missing manifest hashes or incompatible PostgreSQL/Alembic versions; and
- backups stored in the same host/volume failure domain as primary data.

The release manifest must identify the complete deployed artifact set by OCI
digest, configuration revision and opaque secret references. A tag may be
used to build an image but is not a release identity.

One immutable recovery-set manifest must jointly link only cut-time facts:
the quiesced PostgreSQL backup, object snapshot/version or logical
content-root manifest, release digests, configuration revision,
secret-reference versions, compatibility checks, restore order and manifest
hash/signature. Separate, independently selected database and object restores
do not satisfy acceptance. A separate immutable recovery-attempt proof must
reference that set and its manifest hash, and record the post-cut target,
timings, readiness checks and rollback results; those facts must not be added
to the recovery-set manifest.

## 4. Fresh deployment and layered readiness

The fresh-deploy test starts from empty disposable volumes and applies the
existing Alembic chain. It verifies the exact release/configuration manifest
and then proves readiness in layers:

1. container/process liveness;
2. PostgreSQL connectivity and expected migration head;
3. canonical application smoke through the existing supported publication
   paths, without adding an Evidence API;
4. gateway/same-origin browser behavior over organization-trusted HTTPS; and
5. controlled object-fixture access through the storage client.

The existing static `/health` response is useful liveness evidence only. It
cannot alone prove PostgreSQL, migration, object or same-origin readiness.

## 5. Restore and rollback rehearsal

The restore rehearsal uses a distinct clean target and the exact joint
recovery set. It records these pre-cut and post-restore facts:

- database facts and migration head;
- exact `process_review@1` and `compliance_review@1` Scenario publications;
- Activity counts and integrity checks;
- object fixture count and content hashes; and
- absence of unexpected objects or metadata.

The infrastructure fixture must be written directly through the storage
client. It must not create or change Evidence metadata, call an Evidence
upload/download API or imply M6.3 application-level consistency.

Rollback must target an immutable known-good release/configuration set A. The
rehearsal must deploy candidate B, inject a non-secret controlled failure,
stop at the declared condition, roll back to A without restoring the
database, rerun all layered readiness checks and verify the database and
object fixture are unchanged. The recovery-attempt proof records the trigger,
stop condition, failed-target isolation, target set and complete
post-rollback checks. It must not rewrite tags, mutate the source recovery set
or claim success after a partial restore.

## 6. Timing definitions and objectives

All timestamps are ISO 8601 with an explicit offset or UTC `Z`, and the
evidence records the clock source and observed monotonic durations. Define:

```text
recovery_triggered_at       = time the restore decision is made
recovery_set_cut_completed  = completion time of the selected joint cut
restoration_started_at     = time restore actions begin on the clean target
restored_ready_at           = time all layered readiness checks pass

observed RPO = recovery_triggered_at - recovery_set_cut_completed
observed RTO = restored_ready_at - recovery_triggered_at
```

Go requires `observed RPO <= 24 hours` and `observed RTO <= 4 hours` for the
same recovery set. `restoration_started_at` is retained for diagnostic
segment timing only. Approved clean host/container runtime and private
network availability are explicit rehearsal prerequisites and must be
disclosed; they must not be silently removed from the measured RTO. The
evidence must not substitute backup age for a joint cut, or container start
time for restored readiness.

## 7. Sanitized evidence contract

The CI/manual evidence split is explicit:

| Evidence | CI / local validator | Approved private-network manual evidence |
| --- | --- | --- |
| JSON/schema, scope, manifest fields and digest format | Required | Supporting copy only |
| secret/default-credential/raw-key leak scan | Required | Supporting copy only |
| disposable build and static topology checks | Required | Supporting copy only |
| PostgreSQL/Alembic compatibility and restore fixture checks | Required where hermetic | Required for target environment |
| organization-trusted HTTPS/browser behavior | Smoke/contract only | Required |
| negative public-exposure check | Contract/fixture only | Required |
| failure-domain and backup-media proof | Structural check only | Required |
| measured RPO/RTO and rollback rehearsal | Fixture timing only | Required |

Sanitized evidence may contain only:

```json
{
  "recovery_set": {
    "recovery_set_id": "opaque-id",
    "cut_started_at": "timestamp",
    "recovery_set_cut_completed": "timestamp",
    "release_digests": {"api": "sha256:...", "web_gateway": "sha256:..."},
    "config_revision": "opaque-revision",
    "secret_refs": [{"id": "opaque-id", "version": "opaque-version"}],
    "postgres_backup": {"id": "opaque-id", "completed_at": "timestamp"},
    "object_root": {"id": "opaque-id", "count": 0, "content_root": "sha256:..."},
    "schema": {"postgres_major": 17, "alembic_head": "opaque-revision"},
    "restore_order": ["postgres", "object_fixture", "application", "gateway"],
    "manifest_sha256": "sha256:...",
    "signer_key_ref": "opaque-id"
  },
  "recovery_attempt": {
    "recovery_set_id": "opaque-id",
    "manifest_sha256": "sha256:...",
    "target_opaque_id": "opaque-id",
    "recovery_triggered_at": "timestamp",
    "restoration_started_at": "timestamp",
    "restored_ready_at": "timestamp",
    "observed_rpo_seconds": 0,
    "observed_rto_seconds": 0,
    "clock_source": "opaque-reference",
    "checks": {
      "layered_readiness": true,
      "private_tls": {
        "certificate_fingerprint": "sha256:...",
        "issuer_trust_store_ref": "opaque-id",
        "hostname_verified": true,
        "validity_checked": true,
        "probe_at": "timestamp"
      },
      "exposure_probes": [
        {
          "vantage_class": "approved-private",
          "target_fingerprint": "sha256:...",
          "probe_at": "timestamp",
          "result": "reachable",
          "failure_reason_class": null
        },
        {
          "vantage_class": "public-negative",
          "target_fingerprint": "sha256:...",
          "probe_at": "timestamp",
          "result": "not-reachable",
          "failure_reason_class": "no-route"
        }
      ],
      "rollback": {
        "known_good_release_set_id": "opaque-id",
        "failure_injected": "controlled-non-secret",
        "stop_condition": "opaque-class",
        "database_restored_during_rollback": false,
        "layered_readiness_after_rollback": true,
        "fixture_unchanged": true
      }
    }
  }
}
```

The actual evidence must not include credentials, private keys, secret
values, connection strings, customer exports, raw storage keys, hostnames or
network details that would expose the private deployment. Opaque identifiers
must be sufficient for an authorized operator to correlate the underlying
records outside GitHub and C2C.

## 8. No-Go and Implementation Review rules

No-Go applies to any public or wildcard binding, untrusted TLS, leaked or
default credentials, mutable release identity, same-domain backup, stale or
unlinked recovery set, skipped database/object/browser proof, hidden fixture
shortcut, failed rollback isolation, unexpected object/metadata mutation or
scope drift.

Implementation Review requires zero open P1/P2 findings, focused static and
infrastructure tests, the approved private-network PostgreSQL/API/browser
evidence, a current Review Bundle and exact-head GitHub Actions evidence.
Local tests and C2C summaries are supporting evidence only.

M6.1 does not pass merely because the service starts. It passes only when a
fresh no-traffic deployment and a distinct-target restore are both tied to
one immutable recovery set and the measured RPO/RTO, private access and
rollback conditions are all green.

## 9. Next transitions

After the current Gate Draft review passes, update the state only to
`GATE_REVIEW`; this does not authorize implementation. After the separate
Gate Review re-review passes, update the approved scope and enter
`IMPLEMENTATION`. Before Implementation Review, run the focused tests and
generate a current Review Bundle. Before Final Review, run:

```bash
python scripts/easyaudit_gate.py bundle
python scripts/easyaudit_gate.py check --require-clean --require-bundle
```

`FINAL_REVIEW` and `MERGE_AUTHORIZED` require a fixed exact implementation
head, green exact-head GitHub Actions and an explicit user authorization to
merge. M6.1 readiness never authorizes rollout traffic by itself.
