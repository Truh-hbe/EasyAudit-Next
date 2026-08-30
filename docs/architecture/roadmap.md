# 实施路线

This roadmap is rebaselined after the M5 controlled-pilot hardening and the
process Gate finalization PRs.

Current baseline:

```text
main@e643a3f43032908d8a0c59d2f6819ae42d38504a
```

## Completed — M0 Bootstrap

- Python / FastAPI / SQLAlchemy synchronous Session / psycopg 3 / PostgreSQL / Alembic engineering baseline.
- Corrected core concepts, relationship invariants and historical ScenarioVersion addressing.
- Cross-Scenario ReviewPlan, cross-department ActionAssignee and strong-FK persistence rules.
- OpenAPI, containers, automated tests, architecture guards and CI.

## Completed — M1 Platform Foundation

- Organization, Department, User, LocalCredential and server Session.
- Platform role and business relationship separation.
- Persistent ScenarioVersion, Review Core aggregates and append-only Activity.
- Organization-scoped relationship and authorization invariants.

## Completed — M2 Process Review

- `process_review@1` became the first real Scenario over generic Review Core.
- Planning → Case → Finding → rectification Action → Submission → verification → closure is executable end to end.
- Exact Scenario policy owns workflow, authorization, input validation and role specifications.

## Completed — M3 Collaboration & Management

M3 extended the working business core without moving business truth into a second model:

```text
M3.1  Workbench & Query Foundation
M3.2  Persistent Notifications
M3.3  Management Progress Queries
M3.4  Reminder / Nudge
```

The stage established personal work projection, persistent delivery history, management read-side facts and Scenario-owned collaboration recipient semantics.

## Completed — M3.5 Product Surface

M3.5 composed M2 + M3 into the first coherent React product while keeping the backend authoritative for authorization, lifecycle, deadline, recipient and provenance truth.

```text
M3.5.1  Product shell + authentication + navigation
M3.5.2  Workbench + ReviewCase surface
M3.5.3  Finding / Action collaboration surface
M3.5.4  Notification + Management + Reminder actions
M3.5.5  Product acceptance / responsive / final polish
```

M3.5 Final Acceptance passed a real PostgreSQL + FastAPI multi-user Product journey and responsive/accessibility acceptance.

## Completed — M4 Second Scenario Validation

M4 proved that EasyAudit-Next is a reusable audit platform rather than a Process Review application with unused abstractions.

The exact second Scenario is:

```text
compliance_review@1
```

Its material behavior differs from `process_review@1`:

```text
finding_type = observation
OPEN --accept_observation--> CLOSED
```

without manufacturing an ActionItem or rectification Submission. Compliance `nonconformity` continues to use the existing rectification family with persisted responsibility relationships.

M4 preserved the generic platform boundaries:

- both Scenarios use the existing ReviewPlan / ReviewCase / Finding / ActionItem / Submission / Activity model;
- generic HTTP APIs and M3 Workbench / Management / Notification / Reminder-Nudge services are reused rather than copied;
- Review Core and generic application services contain no Scenario-identity business branches;
- exact `(scenario_key, scenario_version)` backend policy and frontend UI adapter resolution remain fail-closed;
- authenticated Users and Departments remain collaboration identities;
- Process Review behavior remains unchanged; and
- the Product Surface now delegates Scenario-specific Finding interactions through the centralized exact-version adapter seam.

M4.1 also exposed and closed the narrow generic direct-Finding-transition abstraction gap. Real PostgreSQL acceptance proved organization isolation and Case-close versus observation-close safety without a new lock architecture. Real FastAPI + Playwright acceptance exercised both Scenarios in the same product build/database.

M4 was intentionally not pre-numbered beyond M4.1. Because the merged M4.1 executable implementation satisfied the complete frozen M4 acceptance objective, no artificial `M4.2` is required solely for numbering continuity.

## Completed — M5 Controlled Pilot

M5.1–M5.4 delivered the controlled-pilot product capabilities while
preserving backend authority, exact Scenario policy and organization
isolation:

```text
M5.1  plan-first planning surface
M5.2  plan-first creation wizard and retry checkpoint
M5.3  Case team and collaboration administration
M5.4  minimal pilot administration and credential recovery
```

M5.5 then hardened the integrated pilot evidence. Its real PostgreSQL/API/
React proof covers clean bootstrap and exact publication, both
`process_review@1` and `compliance_review@1`, plan-first recovery, team safety,
organization isolation and administrator credential reset. M5.5 is complete
as a controlled-pilot evidence slice; it does not claim production deployment,
binary Evidence storage, recurring scheduling or export.

## Next — M6 Controlled Pilot Rollout Readiness v2

M6.0 freezes the bounded rollout plan through a separate docs-only
Architecture / Acceptance Gate. The fixed order and dependencies are:

```text
M6.1  no-traffic private infrastructure + backup/restore
  -> M6.2  Plan/Case idempotency + unknown-result recovery
  -> M6.3  Evidence binary upload + authorized download
  -> M6.4  daily 09:00 Asia/Shanghai one-shot reminder
  -> M6.5  authorized snapshot CSV/XLSX export (max 10,000 rows)
  -> M6 Final Readiness
  -> bounded controlled rollout
  -> five-day soak
  -> Final Review
```

M6.1 is a no-traffic infrastructure Gate with PostgreSQL, private
S3-compatible storage, fixed image digest, configuration/secret references
and RPO/RTO evidence; it does not add Evidence application APIs. M6.2 owns
only the bounded Plan/Case create convergence contract. M6.3 owns the server-
controlled binary/hash/download boundary and keeps pilot Evidence immutable
and non-deletable by end users. M6.4 reuses the scheduler-neutral one-shot
sweep and occurrence-key deduplication without claiming infrastructure
exactly-once delivery. M6.5 produces an authorization-checked, bounded
snapshot rather than a new reporting model.

The pilot envelope is one organization, two departments, 10–20 users and
10–30 Cases, accessed only through an approved private network with
organization-trusted HTTPS. Both exact Scenario versions must be exercised.
Retention expiry, deletion, legal hold, backup-media erasure, external
sharing, public access and unrelated product expansion remain separately
deferred.

Every M6 slice requires its own Gate, scope, implementation review, exact-head
GitHub evidence and final review. This roadmap records dependencies only; it
does not authorize implementation, deployment or real traffic by itself.

## Deferred / non-goals

The following remain deferred unless separately justified by a future Gate:

```text
BPMN / workflow designer
universal form builder
runtime entity designer
custom dashboard builder
anonymous responsibility tokens
SupervisionRecord / ManagementTask domain
native mobile app / offline PWA
AI-generated business truth
```
