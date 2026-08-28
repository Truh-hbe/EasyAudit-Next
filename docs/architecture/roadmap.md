# 实施路线

This roadmap is rebaselined after M3.5 Product Surface completion.

Current baseline:

```text
main@c54600d52e0ace0fa60eb982261ca69dceb416b7
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

## Next — M4 Second Scenario Validation

The original architectural objective of validating a materially different second Scenario remains intentionally unresolved. It moves to M4 rather than being treated as already satisfied by M3 Collaboration & Management.

M4 must prove that EasyAudit-Next is a reusable audit platform rather than a Process Review application with abstractions around it.

The selected reference second Scenario is:

```text
compliance_review@1
```

A narrow compliance / special-review scenario is preferred over a catch-all `general_review` Scenario. The platform is generic; individual Scenarios should remain concrete business contracts.

M4 acceptance must prove at minimum:

- the second Scenario uses the existing ReviewPlan / ReviewCase / Finding / ActionItem / Submission / Activity model;
- existing generic HTTP APIs and M3 read sides are reused rather than copied;
- Review Core and generic application services do not gain `if scenario == ...` business branches;
- exact `(scenario_key, scenario_version)` policy and UI adapter resolution remains fail-closed;
- authenticated users and departments remain the collaboration identities; no anonymous responsibility token model is introduced;
- cross-department, multi-user participation is supported through existing relationship concepts;
- `process_review@1` behavior remains unchanged; and
- the Product Surface evolves its centralized Scenario UI seam instead of distributing second-Scenario branches through generic pages.

### M4.1 — Second Scenario Selection & Extension Contract

First M4 slice. Design/Gate only.

It freezes:

- why `compliance_review@1` is materially different from `process_review@1`;
- which differences belong to Scenario policy/data versus generic Review Core;
- how the existing frontend Scenario adapter must generalize without becoming a second workflow engine;
- reuse requirements for Workbench, Management, Notifications and Reminder/Nudge; and
- implementation acceptance counterexamples before executable work is allowed.

Later M4 slices are not pre-numbered here. Their scope is determined only after M4.1 Architecture + Acceptance Gate review.

## Deferred / non-goals

Do not use M4 as a reason to build a universal low-code platform.

Still deferred unless separately justified:

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
