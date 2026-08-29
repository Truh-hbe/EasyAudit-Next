# 实施路线

This roadmap is rebaselined after M4 Second Scenario Validation completion.

Current baseline:

```text
main@27e750c4901c8abd81b6a55703cd664c237e057e
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

## Next — Separate post-M4 Architecture / Acceptance Gate

The post-M4 milestone is intentionally not named or given executable scope by the M4 finalization PR.

The next product/platform objective must be selected through a separate Architecture / Acceptance Gate based on the highest-value remaining problem after M4 completion.

No executable post-M4 work is authorized merely by this roadmap rebaseline.

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
