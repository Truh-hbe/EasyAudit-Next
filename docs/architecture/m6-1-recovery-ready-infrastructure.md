# M6.1 Recovery-Ready Infrastructure Gate

## Gate status and authorization boundary

This document is the M6.1 Architecture Gate Draft for the EasyAudit-Next
controlled-pilot rollout plan. It defines the smallest executable slice for a
no-traffic private deployment, a jointly verifiable recovery set and a
controlled recovery fixture. It does not authorize implementation until an
independent Architecture / Acceptance Review passes.

The candidate is based exactly on:

```text
main@43fdf9d9a98c3e01d4f2fd50d795567c2fe9a62c
```

The outer lifecycle is:

```text
GATE_DRAFT -> GATE_REVIEW -> IMPLEMENTATION -> FINAL_REVIEW
             -> MERGE_AUTHORIZED -> MERGED
```

For this candidate, a passing `GATE_DRAFT` review authorizes only the
transition `GATE_DRAFT -> GATE_REVIEW`. A separate passing `GATE_REVIEW`
re-review is required before the outer state may transition
`GATE_REVIEW -> IMPLEMENTATION`. During `GATE_REVIEW`, deployment, image
publication, secret access, restore rehearsal and traffic remain forbidden.

While the state is `GATE_DRAFT`, Codex may change only the Gate documents,
state routing and roadmap correction described by the current scope. It must
not create deployment resources, build or publish images, read secrets,
rehearse a restore, expose traffic or modify product behavior.

## Objective and fixed boundary

M6.1 makes the pilot substrate recoverable before any real pilot traffic is
allowed. It proves a fresh, private deployment and a restore/rollback path for
the infrastructure required by the existing product:

- an organization-trusted HTTPS gateway serving the built React product;
- the existing FastAPI application;
- PostgreSQL 17; and
- private S3-compatible object storage.

The slice is infrastructure readiness, not an Evidence lifecycle. It must not
add or change Evidence upload/download APIs, authorization, database/object
compensation semantics, migrations, Scenario policy, Review Core behavior or
business tests. M6.3 retains ownership of application-controlled Evidence
binary storage and the corresponding database/object consistency contract.

The pilot envelope remains one organization, two departments, 10–20 users and
10–30 Cases. M6.1 uses disposable empty volumes and no pilot traffic; test
fixtures are synthetic and must not contain customer exports or production
secrets.

## Private deployment topology

The implementation must use a provider-neutral topology with one externally
reachable component:

```text
approved private/VPN network
          |
       TCP 443
          |
  HTTPS web gateway
      /          \
  static React    /api/v1/*
                     |
                  FastAPI
                     |
               PostgreSQL 17

  controlled recovery utility ──> private S3-compatible storage
```

The gateway is the only component permitted to bind a host port, and that
port must be an explicitly supplied approved private/VPN address. API,
PostgreSQL, object API and any administration console have no published host
ports. Container-to-container traffic uses the private deployment network.

The gateway serves the built React product and proxies relative `/api/v1/*`
requests through the same HTTPS origin. The Vite development server and
`basicSsl` certificate are not pilot deployment mechanisms. The certificate
chain must be trusted by the organization from the approved network, and a
negative public-exposure check is required before the environment can be
called private.

The M6.1 application runtime has no S3 configuration and no object-store
access. Only the controlled recovery utility may use the storage client for
the infrastructure fixture. M6.3 owns the later application-level object
connection and Evidence consistency contract.

The existing `compose.yaml` is a development-only fixture: it publishes
internal ports and contains default credentials. It is not the M6.1 pilot
deployment artifact and must not be widened into one.

## Immutable release and configuration identity

Every deployed application or service image is identified by an immutable
OCI digest. The release set must include the API image and the web/gateway
artifact that serves the React build; an API-only digest is not a complete
product identity. Mutable tags may be used only as a build input and must not
appear as deployment identity.

The release manifest records:

- release-set identifier and creation time;
- API, web/gateway and PostgreSQL/object-storage image digests, when the
  service is image-backed;
- application and infrastructure configuration revision;
- schema and Alembic head compatibility;
- opaque secret-reference identifiers and versions; and
- SHA-256 hashes for the manifest and any non-secret release metadata.

Runtime certificates, database/object credentials and private configuration
remain outside Git, image layers, logs, Review Bundles and C2C messages. The
manifest contains only opaque reference identifiers and versions, never secret
values, private keys, connection strings, raw access tokens or raw object
keys. `deploy/private/` and any secret material must be excluded from Git and
Docker build context before runtime files can exist.

## Joint recovery set

The recovery unit is one quiesced, jointly verifiable cut rather than an
unrelated PostgreSQL backup plus an independently selected object snapshot.
The immutable recovery-set manifest may contain only facts known at cut time
and must link:

1. `recovery_set_id`, cut start/end timestamps, an immutable manifest hash and
   detached signature/key reference;
2. PostgreSQL backup identity, backup completion time, PostgreSQL major
   version and the expected Alembic head;
3. an object-store snapshot/version or a content-root manifest with fixture
   object count and content hashes, using logical identifiers rather than raw
   storage keys;
4. every deployed image digest in the release set;
5. configuration revision and opaque secret-reference identifiers/versions;
6. restore order and compatibility checks; and
7. non-secret evidence timestamps needed to verify the cut.

The backup must be outside the primary service volumes and in a separately
recoverable failure domain. A backup on the same host or volume is a No-Go.
The recovery cut is quiesced so the database facts, object fixture and
release/configuration identity can be validated against one explicit point in
time. The fixture is written directly through the controlled storage client;
it must not call an Evidence API, create Evidence metadata or claim
application-level database/object consistency.

The recovery-set manifest is immutable after the cut. A separate immutable
recovery-attempt proof is created for each rehearsal. It references
`recovery_set_id` and the manifest hash, then records the opaque clean-target
identifier, `recovery_triggered_at`, `restoration_started_at`,
`restored_ready_at`, layered check results and rollback results. Post-cut
facts are never written back into the recovery-set manifest. Approved clean
host/container runtime and private-network prerequisites must be disclosed in
the proof; they are prerequisites of the rehearsal, not time silently
subtracted from its RTO. `restoration_started_at` remains a diagnostic
segment timestamp.

## Restore, rollback and stop conditions

Restore rehearsal follows the manifest order into a distinct clean target:

1. provision empty disposable database, object and application volumes;
2. validate image digests, configuration revision, secret-reference
   availability and PostgreSQL/Alembic compatibility;
3. restore PostgreSQL and verify the expected migration head;
4. restore the object fixture or content-root manifest;
5. start the gateway and application with no public binding;
6. prove layered readiness and same-origin private HTTPS behavior; and
7. compare pre-cut and restored database facts, Scenario publications,
   Activity counts/integrity, fixture object count and content hashes.

The rollback rehearsal is explicit and controlled: prepare a known-good
release/configuration set A, deploy candidate set B, inject a non-secret
controlled failure into B, and stop at the declared failure condition. Roll
back to immutable set A without restoring the database or mutating the source
recovery set; then rerun every layered readiness check and verify that the
database and object fixture remain unchanged. The recovery-attempt proof
records the rollback trigger, stop condition, target release-set identifier,
failed-target isolation and all post-rollback checks before any retry.

Immediate No-Go conditions include public exposure, a non-trusted or
self-signed pilot certificate, any published internal port, a mutable image
identity, missing or leaked secret references, a same-failure-domain backup,
an unlinked database/object cut, an unclean restore target, an incompatible
schema/image pair, skipped PostgreSQL or browser proof, hidden fixture
shortcuts, or any application-layer Evidence/API change.

## Prospective implementation allowlist

After Gate Review passes, implementation is limited to:

```text
.easyaudit/development-state.json
docs/architecture/roadmap.md
docs/architecture/m6-1-recovery-ready-infrastructure.md
docs/architecture/m6-1-acceptance.md
docs/operations/m6-1-recovery-runbook.md
.gitignore
.dockerignore
Dockerfile
deploy/m6-1/**
scripts/m6_1_recovery.py
tests/infrastructure/test_m6_1_*.py
tests/tooling/test_m6_1_*.py
.github/workflows/m6-1-recovery.yml
```

The development `compose.yaml`, `src/**`, `alembic/**`, `openapi/**`,
`web/**`, existing API/browser business tests and unrelated deployment
resources remain outside scope. If the implementation needs application or
configuration source changes outside this allowlist, stop and revise this
Gate before continuing.

## Gate exit criteria

The current `GATE_DRAFT` can pass only when:

- the architecture and acceptance documents freeze the topology, trust
  boundary, immutable release set, secret/config references, failure domain,
  recovery ordering, rollback and exclusions;
- the prospective allowlist is narrow and machine-readable in the state file;
- static checks, `git diff --check`, the active Gate check and a clean Review
  Bundle pass; and
- ChatGPT independently reviews the current candidate and authorizes only
  `GATE_DRAFT -> GATE_REVIEW`.

The later `GATE_REVIEW` can authorize `GATE_REVIEW -> IMPLEMENTATION` only
after its separate re-review passes. No deployment resources, image
publication, secret access, restore rehearsal or traffic may occur while that
re-review is pending.

Implementation Review must then prove the acceptance matrix in
`m6-1-acceptance.md`. A local pass or a roadmap entry never authorizes real
traffic or a merge.
