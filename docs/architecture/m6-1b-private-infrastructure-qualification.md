# M6.1b Real Private-Network Infrastructure Qualification Gate

## Status and purpose

M6.1b is the executable private-network infrastructure qualification slice for
EasyAudit-Next. It builds upon the recovery contract and tooling established in
M6.1a (`M6.1a-recovery-contract-tooling`) and executes a real qualification
against an approved private environment using synthetic fixtures and disposable
volumes.

The candidate is based on:

```text
main@c989629b32cb115f84ec869852af9356ea4877a1
```

Predecessors required and verified in base ancestry:

1. `M6.1a-recovery-contract-tooling` (PR #40)
2. `process-omp-agent-control-plane-implementation` (PR #45)

M6.1b qualifies the real deployment substrate, disaster-recovery cut, clean-target
restore, rollback rehearsal and measured RPO/RTO against the versioned recovery
contracts (`deploy/m6-1/contracts/**`).

M6.1b remains a strictly **no-traffic** qualification. It uses disposable empty
volumes and synthetic test fixtures. It does not authorize pilot users,
application Evidence APIs, or production rollout.

## Fixed boundary and relationship to other slices

M6.1b owns:

- Provider-neutral private deployment runtime definitions under `deploy/m6-1/**`.
- Container non-root and minimal-privilege configuration.
- Single entrypoint HTTPS gateway reverse proxy binding exclusively to an approved private/VPN address.
- Negative public-exposure verification proving no internal service (FastAPI, PostgreSQL 17, MinIO S3 object storage) publishes host ports.
- Joint PostgreSQL and object storage recovery cut execution within an atomic/bounded window.
- Separate backup failure domain storage isolation.
- Fresh deployment from disposable empty volumes.
- Clean target restoration and verification against expected Alembic migration head.
- Layered post-restore readiness checks: HTTP health probes and synthetic browser journey.
- Post-restore cross-tenant read negative test ensuring department isolation.
- Controlled rollback rehearsal to an immutable known-good release without restoring the database.
- Real RPO / RTO duration measurement and arithmetic contract validation.
- Automated infrastructure qualification test suite and qualification script under `deploy/m6-1/` and `tests/infrastructure/`.

M6.1b explicitly does **not** own:

- Review Core logic, Scenario policies, or domain invariants (`src/**` is forbidden).
- Database migrations or schema evolution (`alembic/**` is forbidden).
- Frontend application code or React UI features (`web/**` is forbidden).
- Application-level Evidence upload/download APIs (owned by M6.3).
- Rollout-final Release Candidate qualification (owned by M6-RC after M6.1–M6.5 stabilize).

## Private deployment topology

The pilot infrastructure substrate contains only the minimum required runtime:

```text
approved private / VPN network interface
                   |
            HTTPS (TCP 443)
                   |
       organization-trusted TLS gateway
           /                  \
   static React UI          /api/v1/*
                                |
                             FastAPI
                                |
                          PostgreSQL 17

   controlled recovery utility ──> private S3-compatible object storage
```

### Network isolation invariants

1. **Single Entrypoint**: The HTTPS gateway is the only externally reachable component. It binds exclusively to the operator-specified private IP / interface.
2. **No Port Leakage**: FastAPI (`8000`), PostgreSQL (`5432`), and S3-compatible object storage (`9000`, `9001`) run on internal container networks only and must not publish host ports.
3. **Provider-Neutral Runtime**: The substrate configuration is containerized and provider-neutral, operating identically on local Docker Compose or private cloud container hosts.

## Joint Recovery Cut Contract

A valid joint recovery cut must satisfy the M6.1a contract:

1. **Inclusive Cut Window**:
   ```text
   cut_started_at
     <= postgres_backup.completed_at
     <= recovery_set_cut_completed

   cut_started_at
     <= object_root.captured_at
     <= recovery_set_cut_completed
   ```
2. **Failure Domain Separation**: The backup artifact target location must be distinctly separate from primary application volume mounts.
3. **Release Set Parity**: The `recovery-set.json` must exactly match the release digests, configuration revision, and schema head declared in `release-manifest.json`.
4. **Integrity Hashing**: Canonical SHA-256 hashes must be recomputed and match the contract schemas.

## Clean Target Restoration & Layered Verification

Restoration qualification proves that the system can be fully recovered onto a clean, distinct target from backup artifacts:

1. **Empty Volume Provisioning**: Target database and object storage volumes start completely empty.
2. **Restore Execution Order**:
   - Restore object storage bucket content from the joint cut.
   - Restore PostgreSQL relational dump from the joint cut.
3. **Schema Verification**: Verify the restored database matches the exact expected Alembic revision head.
4. **Layered Readiness Probes**:
   - HTTP health probe on the API service (`/health` or `/api/v1/cases`).
   - Browser / Playwright automated verification against the HTTPS gateway confirming login, workbench queries, and case navigation succeed against restored data.
5. **Multi-Tenant Isolation Invariant**: Verification that restored synthetic data across distinct organizations/departments remains inaccessible across tenant boundaries.

## Controlled Rollback Qualification

Rollback qualification proves operational safety when rolling back application versions without destroying database state:

1. Rollback application image to an immutable known-good release.
2. Execute rollback **without** restoring or dropping the PostgreSQL database.
3. Verify backward schema and data compatibility: existing database records and object references remain fully accessible.

## Measured RPO & RTO

The recovery attempt must measure real execution timing and satisfy:

```text
Measured RPO = recovery_triggered_at - recovery_set_cut_completed <= 24 hours (86,400s)
Measured RTO = restored_ready_at - recovery_triggered_at <= 4 hours (14,400s)
```

The measured timestamps and durations are captured in `recovery-attempt.json` and validated by `scripts/m6_1_recovery.py validate`.

## Security and Sanitization

- Synthetic test data only; zero customer data or production secrets.
- Opaque secret references (`secret_references`) rather than plaintext credentials.
- Non-root container execution across all services.
- Diagnostics and logs must remain leak-safe and redact sensitive tokens.
