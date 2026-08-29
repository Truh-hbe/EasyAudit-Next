# M4 Final — Second Scenario Validation Completion Review

Baseline:

```text
main@27e750c4901c8abd81b6a55703cd664c237e057e
```

This is a **docs-only finalization review** after M4.1 merged through PR #26. It does not authorize further M4 executable implementation.

## 1. Purpose

M4 existed to prove that EasyAudit-Next is a reusable audit platform rather than a `process_review` application whose generic abstractions had never been exercised by a materially different Scenario.

The roadmap deliberately did not pre-number later M4 slices. Their scope was to be determined only after M4.1 Architecture + Acceptance review.

M4.1 has now gone beyond selection/design and completed the executable second-Scenario proof. This review therefore asks one question:

> Is any additional M4 slice required to satisfy the already-frozen M4 acceptance objective?

If the answer is no, M4 closes here rather than manufacturing an artificial `M4.2`.

## 2. M4.1 merged evidence

PR #26 merged from the exact Final Review head:

```text
fixed head:
c02e6901a900807db1b3a51ed36f68e479af63d3

fixed tree:
047553fa7a340f52d1845923a4529fa5546b9db3

exact-head CI:
#391 — completed / success

merge commit:
27e750c4901c8abd81b6a55703cd664c237e057e
```

The merge commit has exactly these parents:

```text
c54600d52e0ace0fa60eb982261ca69dceb416b7
c02e6901a900807db1b3a51ed36f68e479af63d3
```

and preserves the Final Review tree:

```text
047553fa7a340f52d1845923a4529fa5546b9db3
```

## 3. Second Scenario is materially real

The exact second Scenario is:

```text
compliance_review@1
```

It owns Scenario-specific Case data:

```text
standard_reference
scope_summary
```

and Finding data:

```text
criterion_reference
finding_type = observation | nonconformity
```

The material counterexample is executable:

```text
observation
OPEN --accept_observation--> CLOSED
```

without fabricating an ActionItem or rectification Submission.

A `nonconformity` uses the existing rectification family and requires persisted `responsible_department + owner` before issuance.

`process_review@1` continues to reject `accept_observation`.

## 4. Generic architecture was exercised rather than copied

M4.1 proved both exact Scenario policies execute through the same generic domain/application stack.

No Compliance-specific copies were introduced for:

```text
ReviewCase / Finding / ActionItem / Submission
HTTP endpoint families
Workbench
Management
Notification
Reminder / Nudge
```

The composition root registers exact immutable policies while generic Review Core and application services remain free of `if scenario == ...` business branches.

The generic Finding transition path now consumes an exact Scenario-owned direct transition decision:

```text
Scenario-neutral current facts
→ exact Scenario decision
→ required_permission + target_lifecycle
→ generic authorization
→ generic CAS persistence
→ generic finding.transitioned Activity
```

Generic code does not interpret Compliance `finding_type`.

## 5. Authorization, identity and concurrency proof

M4.1 executable acceptance proved:

- authenticated Users and Departments remain the only ordinary collaboration identities;
- same-organization invisible actors cannot obtain Scenario validation details before `view_finding` authorization;
- cross-Organization persisted Case/User, Finding/User, Finding/Department, Action/User and Action/Department relationships are rejected by real PostgreSQL constraints;
- Case closure racing `accept_observation` never commits `ReviewCase=CLOSED` with a non-terminal child Finding; and
- the existing serialization model was sufficient, so no new lock architecture was added.

## 6. M3 reuse proof

The same persisted Compliance resources were exercised through the existing:

```text
WorkbenchQueryService
ManagementQueryService
ManualNudgeService
NotificationService
```

No second read-side or collaboration truth was introduced.

The Product nudge request remains recipient-free; recipient semantics stay server/Scenario-owned.

## 7. Product Surface proof

The generic Finding detail page no longer owns Process Review-shaped workflow UI.

Exact-version adapters own Scenario-specific interaction presentation:

```text
process_review@1
compliance_review@1
```

Resolution is exact `(scenario_key, scenario_version)` only. There is no key-only, latest, nearest or cross-Scenario fallback.

Scenario adapters reuse shared command ports, shared server error handling and authoritative refetch. They do not become a second workflow engine.

## 8. Real Product acceptance

CI #391 executed real PostgreSQL + Alembic + FastAPI + Playwright acceptance.

The real browser suite completed:

```text
6 passed
```

The Compliance journey authenticated a real user, discovered the Compliance Case from Workbench, rendered exact Scenario fields through shared Product routes, opened an observation Finding, confirmed no synthetic Action/Submission, submitted `accept_observation` through the shared transition endpoint and observed authoritative `CLOSED` plus generic `finding.transitioned` history.

Existing Process Review browser journeys remained green in the same run.

## 9. M4 completion decision

The original M4 minimum acceptance is now satisfied:

- existing Review Core entities reused;
- generic HTTP APIs reused;
- M3 read sides/collaboration reused;
- no generic Scenario identity branches;
- exact-version backend and UI resolution fail closed;
- authenticated User/Department identity preserved;
- cross-department multi-user participation preserved;
- Process Review behavior preserved; and
- Product Surface Scenario seam exercised by a materially different second Scenario.

Therefore this review proposes:

```text
M4 Second Scenario Validation
→ COMPLETE
```

No additional `M4.2` is required merely for numbering continuity.

## 10. Scope boundary

This finalization PR may change only:

```text
docs/architecture/roadmap.md
docs/architecture/m4-final-second-scenario-validation.md
docs/architecture/m4-final-acceptance.md
```

Forbidden in this PR:

```text
src/**
web/**
tests executable source
alembic/**
OpenAPI artifacts
package / lockfile
workflow / CI
```

## 11. Next milestone boundary

This review intentionally does **not** invent or name the post-M4 implementation stage.

The next milestone must be selected through a separate Architecture / Acceptance Gate based on the product/platform objective chosen after M4 completion.

Deferred/non-goal items remain deferred unless separately justified, including universal workflow/BPMN, universal form/runtime entity builders, anonymous responsibility tokens, custom dashboard builders and AI-generated business truth.
