# M3.3 — Management Progress & Overdue Queries

M3.3 is the third Collaboration & Management slice. It builds on the merged M3.1 Workbench query foundation and M3.2 persistent Notification foundation, but it remains a read-side management projection.

Its purpose is to answer a different question from the personal Workbench:

> **For the ReviewCases I am actually authorized to manage, where is progress now and what is already late?**

M3.3 must not create a second workflow truth, must not invent generic management roles, and must not start M3.4 reminder/nudge behavior.

## Goal

Provide bounded authenticated management queries for ReviewCase progress and overdue conditions using existing M2 business facts and exact historical Scenario authorization.

The first API surface is expected to include:

```http
GET /api/v1/management/review-cases
GET /api/v1/management/review-cases/{case_id}/progress
```

The collection endpoint is the dashboard/query surface. The detail endpoint is a read-only progress drill-down for one managed ReviewCase.

Exact route naming may be adjusted during implementation if required by the existing API layout, but the capability boundary in this document is fixed.

## M3.3 is a projection, not a new management domain

M3.3 must not persist:

- `ManagementCase`;
- `SupervisionTask`;
- `ManagementStatus`;
- `ProgressSnapshot`;
- `OverdueRecord`;
- `AttentionItem`;
- a second responsibility table; or
- any equivalent materialized business truth.

Authoritative state remains:

```text
ReviewCase / CaseMember
Finding / FindingParticipant
ActionItem / ActionAssignee
Submission
Activity
ScenarioPolicy.authorization
```

M3.3 may compute DTO fields such as lifecycle counts and overdue counts at query time. Those values are presentation projections only.

## Management scope

EasyAudit-Next currently has no organization-wide business `manager` role and M3.3 must not invent one.

The first management query scope is intentionally narrow:

1. the caller must be an active BusinessIdentity in the same Organization;
2. the caller must have a direct CaseMember relationship on the candidate ReviewCase; and
3. the exact persisted ScenarioVersion for that ReviewCase must allow the existing Scenario permission:

```text
manage_case_members
```

for the target Case authorization context.

The Case must also satisfy the normal exact-policy `view_case` check before it can appear.

This deliberately reuses an existing Scenario-owned case-management capability rather than adding a new platform role or hard-coding `role_key == lead`.

For `process_review@1`, `lead` currently satisfies this permission. M3.3 code must not know that fact.

A future requirement for read-only supervisors who can oversee a Case without `manage_case_members` authority is a separate Scenario-contract change and is outside this slice.

`system_admin` receives no implicit M3.3 business scope.

## Exact historical Scenario authorization

Every candidate ReviewCase is interpreted using its persisted historical:

```text
scenario_key + scenario_version
```

The query must call the exact `ScenarioPolicy.authorization` registered for that version.

Forbidden shortcuts include:

```text
role_key == "lead"
platform_role == "system_admin"
latest ScenarioVersion
Scenario key without version
organization-wide manager flag
```

M3.3 must preserve the target-scoped authorization rule established in M3.1:

```text
bulk SQL fetch
    ↓
group relationship facts by target
    ↓
assemble exact AuthorizationContext
    ↓
ScenarioPolicy.authorization.allows(...)
```

Bulk loading is a database optimization, never an authorization-scope shortcut.

## Visibility of child progress

A Case-level management permission does not automatically permit disclosure of arbitrary child data in every future Scenario.

For each Finding included in the progress projection, M3.3 must evaluate the exact Scenario `view_finding` permission using the target Finding authorization context.

Therefore:

- visible Finding lifecycle counts may include only Findings the caller is authorized to view;
- Action progress may be aggregated only under Findings the caller is authorized to view; and
- hidden sibling Findings/Actions must not leak through counts, overdue totals, severity totals, identifiers, or derived metrics.

For `process_review@1`, a lead's Case role currently grants `view_finding`, so the management projection is complete for that Case. The query layer must not rely on that Process Review fact.

If a future Scenario grants case-management authority while intentionally hiding some child resources, M3.3 must return an authorization-safe partial projection rather than silently leaking hidden aggregate facts.

## Progress model

M3.3 does not invent a generic percent-complete formula.

A percentage such as `73% complete` would require cross-Scenario semantics for weighting Cases, Findings and Actions that do not currently exist.

The first progress projection is therefore factual and count-based.

### ReviewCase facts

Each management Case summary may expose:

```text
id
review_plan_id
title
scenario_key
scenario_version
lifecycle
planned_start_at
planned_end_at
```

plus derived deadline status.

### Finding progress

For authorized Findings under the Case, aggregate exact persisted lifecycle facts such as:

```text
total
open
rectifying
verifying
closed
voided
```

and, where useful for display, severity counts derived from persisted `Finding.severity`.

M3.3 must not collapse Finding lifecycle into a new persisted `progress_status`.

### Action progress

For Actions belonging to authorized Findings, aggregate exact persisted lifecycle facts such as:

```text
total
todo
in_progress
done
cancelled
overdue
```

The progress detail may additionally group Action counts by Finding so management users can see where unfinished work is concentrated.

## Deadline semantics

M3.3 must reuse the deadline semantics already frozen by M3.1.

At one captured timezone-aware `as_of` value:

```text
ReviewCase overdue
= planned_end_at < as_of
  AND lifecycle in {scheduled, in_progress}

ActionItem overdue
= due_at < as_of
  AND lifecycle in {todo, in_progress}
```

Terminal states are excluded.

For due-soon presentation, M3.3 may reuse the same seven-day projection window:

```text
as_of <= deadline <= as_of + 7 days
```

This remains a read-model window only.

### No generic Finding deadline in M3.3

M3.1 intentionally deferred the question of a generic Finding deadline.

M3.3 does **not** establish enough cross-Scenario evidence to add one merely for dashboard convenience.

Therefore M3.3 must not derive a Finding deadline from:

- `scenario_data`;
- the earliest or latest Action `due_at`;
- ReviewCase `planned_end_at`;
- Submission timestamps; or
- any heuristic.

If a future Scenario proves that `Finding.due_at` is a real cross-Scenario business fact, that domain change requires a separate architecture review.

## Collection query

`GET /api/v1/management/review-cases` should provide a bounded deterministic list of managed Case summaries.

The first slice may support filters that correspond to real persisted/projected facts, such as:

```text
review_plan_id
lifecycle
deadline_status = all | due_soon | overdue
limit
offset
```

Filters must not change authorization scope.

The response should expose enough factual aggregates for a management dashboard without requiring one HTTP request per Case.

At minimum each returned Case summary should include:

- Case identity and lifecycle;
- planned deadline facts;
- Finding lifecycle counts for authorized Findings;
- Action lifecycle counts for authorized Findings;
- overdue Action count; and
- derived Case deadline bucket/status.

The endpoint must not expose Notification state as management truth.

## Progress detail query

`GET /api/v1/management/review-cases/{case_id}/progress` returns a read-only drill-down for one managed Case.

It may include:

- the same Case summary facts;
- Finding-level progress rows for authorized Findings;
- per-Finding Action lifecycle counts;
- overdue/due-soon Action counts or bounded Action deadline items; and
- one captured `as_of` timestamp for all deadline calculations in the response.

The detail endpoint must not become an alternate unrestricted ReviewCase API.

Known foreign or unauthorized UUIDs must not disclose whether a Case exists.

## Deterministic ordering

The first collection order should make risk visible and remain stable.

A suitable order is:

1. overdue Cases first;
2. then non-overdue Cases by nearest `planned_end_at`;
3. null deadlines after dated Cases; and
4. stable Case UUID as the final tie-breaker.

Within progress detail:

- overdue Actions: oldest deadline first;
- due-soon Actions: nearest deadline first;
- Findings: stable deterministic order, preferably `raised_at` then id.

Ordering is a read-model concern only.

## Query implementation boundary

M3.3 should live in a dedicated read-side module, for example:

```text
src/easyaudit_next/management/
    query_service.py
    schemas.py
    api.py
```

It may read SQLAlchemy persistence records directly or through a dedicated management read repository.

It must not add management-only methods to the base `ReviewCoreRepository`.

It must not make Review Core import `management`, `workbench`, or `notifications`.

M3.3 should reuse target-context assembly patterns from M3.1 where practical, but must not copy the Process Review role matrix into a second module.

A small shared read-side authorization-context helper is acceptable only if it remains Scenario-neutral and does not create a second authorization policy.

## Query performance boundary

The collection endpoint is specifically intended to avoid a dashboard N+1 pattern.

Implementation should bulk-fetch or aggregate by query category, for example:

```text
candidate Case memberships
Case rows + ScenarioVersion/Scenario metadata
Case/Finding/Action relationship facts
Finding lifecycle aggregates
Action lifecycle/deadline aggregates
```

The exact SQL shape is implementation-owned, but SQL statement growth must be category-bounded rather than proportional to returned Case count or child resource count.

PostgreSQL integration tests must compare materially different data sizes and prove that returning more managed Cases does not introduce per-Case query loops.

M3.3 may add read-side indexes justified by actual executed queries or PostgreSQL plans. It must not add denormalized management tables or redundant indexes merely to match a design sketch.

## Organization and privacy boundary

Every query is constrained by the authenticated user's `organization_id` before materialization.

The management API must not expose:

- another Organization's Cases;
- same-Organization Cases the caller is not authorized to manage;
- existence of a Case merely because its UUID is known;
- hidden Finding or Action counts;
- `system_admin` bypass data; or
- aggregate totals that include unauthorized resources.

## No M3.4 behavior

M3.3 does not send, create, schedule, or retry reminders.

Specifically it must not add:

- manual nudge/remind actions;
- automatic overdue scanning;
- scheduler/cron/background jobs;
- reminder cadence;
- escalation rules;
- snooze;
- notification preferences;
- email/webhook/IM/push delivery; or
- new Notification kinds for deadline reminders.

M3.4 may later consume the M3.2 Notification foundation and M3.3 management/deadline projection, but that future behavior requires its own Gate.

## Explicitly out of scope

M3.3 does not add:

- new Review Core lifecycle states or transitions;
- a generic business `manager`/`supervisor` platform role;
- org-wide management access;
- ReviewPlan mutation expansion;
- Finding deadline persistence;
- percent-complete business semantics;
- progress snapshots/materialized views as business truth;
- management write actions;
- Notification-driven authorization;
- reminders or nudges;
- a second Scenario; or
- frontend dashboard UI.

## End state

M3.3 is complete when an authenticated user can query only the ReviewCases that the exact historical Scenario Policy authorizes them to manage, obtain factual Case/Finding/Action progress and overdue projections with no hidden-child leakage, and do so with category-bounded PostgreSQL queries while Review Core, Notification semantics, and M3.4 reminder behavior remain unchanged.
