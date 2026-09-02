# M6.1b Real Private-Network Infrastructure Qualification Acceptance

## 1. Scope and Predecessor Acceptance

M6.1b is accepted for implementation and review only when the PR is based on:

```text
main@c989629b32cb115f84ec869852af9356ea4877a1
```

and the verified predecessors in `main` ancestry include:

1. `M6.1a-recovery-contract-tooling` (PR #40)
2. `process-omp-agent-control-plane-implementation` (PR #45)

The final `main...HEAD` changed-file set must be strictly contained within:

```text
.easyaudit/development-state.json
deploy/m6-1/**
scripts/m6_1*
tests/tooling/test_m6_1_recovery_contracts.py
tests/infrastructure/**
docs/architecture/m6-1b*
docs/architecture/roadmap.md
```

The following paths are strictly forbidden and must not be modified:

```text
.easyaudit/workflow-policy.json
src/**
alembic/**
web/**
```

No Review Core logic, Scenario permission models, database migrations, or React
UI components may be changed in this slice.

## 2. Private Deployment Substrate Acceptance

Acceptance requires:

1. **Provider-Neutral Topology**: The deployment configuration in `deploy/m6-1/` defines a containerized environment with:
   - TLS / HTTPS gateway reverse proxy;
   - FastAPI application;
   - PostgreSQL 17;
   - S3-compatible object storage (e.g. MinIO); and
   - Controlled backup/restore recovery utility.
2. **Single Entrypoint Invariant**: The HTTPS gateway is the only externally reachable component. It must bind exclusively to an explicitly specified private host interface (e.g. `127.0.0.1` or approved private/VPN IP).
3. **Negative Port Exposure Verification**: Automated qualification probes prove that internal ports for FastAPI (`8000`), PostgreSQL (`5432`), and Object Storage (`9000`, `9001`) are not bound to `0.0.0.0` or any unapproved host interfaces.
4. **Non-Root Execution**: Container definitions enforce non-root user execution with minimal required capabilities.

## 3. Joint Recovery Cut Acceptance

Acceptance requires:

1. **Inclusive Joint Cut Window**:
   - Execution of a real joint backup cut producing `release-manifest.json` and `recovery-set.json`.
   - `postgres_backup.completed_at` and `object_root.captured_at` fall strictly within `[cut_started_at, recovery_set_cut_completed]`.
2. **Failure Domain Separation**: Backup artifacts are stored in an isolated failure domain distinct from primary volume storage.
3. **Detached Signature and Integrity**:
   - Manifest SHA-256 is recomputed and verified against committed schemas.
   - Detached signature reference is recorded.
4. **Contract Tooling Validation**: `python scripts/m6_1_recovery.py validate` passes on the cut artifacts with zero errors.

## 4. Clean Target Restoration & Layered Readiness Acceptance

Acceptance requires:

1. **Empty Volume Target**: Restoration executes against a fresh, completely empty target volume set.
2. **Restore Order**:
   - S3 object storage state restored first;
   - PostgreSQL relational backup restored second.
3. **Migration Head Validation**: Restored database is verified against the expected Alembic revision head.
4. **Layered Readiness Verification**:
   - API service health probes respond with 200 OK.
   - Synthetic browser / E2E journey executes against the restored target over HTTPS, verifying successful authentication, workbench list querying, and Case detail viewing.
5. **Multi-Tenant Isolation Invariant**: Restored synthetic multi-department data is verified to maintain strict department isolation (users cannot access cross-department Cases).

## 5. Controlled Rollback Qualification Acceptance

Acceptance requires:

1. Application container image rolled back to an immutable known-good release reference.
2. Rollback executed **without** restoring or dropping the PostgreSQL database.
3. Backward schema and data compatibility verified: existing database rows and object references remain accessible and undamaged after rollback.

## 6. Measured RPO & RTO Acceptance

Acceptance requires:

1. Authoritative arithmetic validation:
   ```text
   Observed RPO = recovery_triggered_at - recovery_set_cut_completed <= 24 hours (86,400s)
   Observed RTO = restored_ready_at - recovery_triggered_at <= 4 hours (14,400s)
   ```
2. Real execution duration measured and captured in `recovery-attempt.json`.
3. `python scripts/m6_1_recovery.py validate` confirms valid arithmetic and schema compliance.

## 7. Automated Qualification Test Suite Acceptance

Acceptance requires:

1. Automated qualification suite under `tests/infrastructure/` and tooling tests under `tests/tooling/` pass completely.
2. Setup and teardown of disposable containers and temporary test volumes are hermetic and leave no leaked resources or background processes.
3. Zero flaky assertions.

## 8. Non-Authorization & Governance Invariants

Acceptance requires:

1. Zero open P0 and zero open P1 defects.
2. M6.1b is a private, synthetic no-traffic qualification only. It does not authorize real pilot traffic, user onboarding, Evidence upload APIs, or production rollout.
3. Final merge authorization requires explicit Human Maintainer approval and green CI on the exact fixed candidate HEAD.
