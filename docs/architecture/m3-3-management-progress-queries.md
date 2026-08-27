# M3.3 — Management Progress & Overdue Queries

M3.3 is the third Collaboration & Management slice. It builds on the merged M3.1 Workbench query foundation and M3.2 persistent Notification foundation, but it remains a read-side management projection.

Its purpose is to answer a different question from the personal Workbench:

> **For the ReviewCases I am actually authorized to manage, where is progress now and what is already late?**

M3.3 must not create a second workflow truth, must not invent generic management roles, and must not start M3.4 reminder/nudge behavior.

## Goal

Provide bounded authenticated management queries for ReviewCase progress and overdue conditions using existing M2 business facts and exact historical Scenario authorization.

The first API surface is:

```http
GET /api/v1/management/review-cases
GET /api/v1/management/review-cases/{case_id}/progress
```

The collection endpoint is the dashboard/query surface. The detail endpoint is a read-only progress drill-down for one managed ReviewCase.

## M3.3 is a projection, not a new management domain

M3.3 does not persist:

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

M3.3 computes DTO lifecycle and overdue counts at query time. Those values are presentation projections only.

## Management scope

EasyAudit-Next currently has no organization-wide business `manager` role and M3.3 does not invent one.

The management query scope is:

1. the caller is an active BusinessIdentity in the same Organization;
2. the caller has a direct CaseMember relationship on the candidate ReviewCase; and
3. the exact persisted ScenarioVersion for that ReviewCase allows the existing Scenario permission:

```text
manage_case_members
```

for the target Case authorization context.

The Case must also satisfy the normal exact-policy `view_case` check before it can appear.

This deliberately reuses an existing Scenario-owned case-management capability rather than adding a new platform role or hard-coding `role_key == lead`.

For `process_review@1`, `lead` currently satisfies this permission. M3.3 code does not know or test that fact.

A future requirement for read-only supervisors who can oversee a Case without `manage_case_members` authority is a separate Scenario-contract change and is outside this slice.

`system_admin` receives no implicit M3.3 business scope.

## Exact historical Scenario authorization

Every candidate ReviewCase is interpreted using its persisted historical:

```text
scenario_key + scenario_version
```

The query calls the exact `ScenarioPolicy.authorization` registered for that version.

Forbidden shortcuts remain:

```text
role_key == "lead"
platform_role == "system_admin"
latest ScenarioVersion
Scenario key without version
organization-wide manager flag
```

M3.3 preserves the target-scoped authorization rule established in M3.1:

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

For each Finding included in the progress projection, M3.3 evaluates the exact Scenario `view_finding` permission using the target Finding authorization context.

Therefore:

- visible Finding lifecycle counts include only Findings the caller is authorized to view;
- Action progress is aggregated only under Findings the caller is authorized to view; and
- hidden sibling Findings/Actions do not leak through counts, overdue totals, severity totals, identifiers, or derived metrics.

For `process_review@1`, a lead's Case role currently grants `view_finding`, so the management projection is complete for that Case. The query layer does not rely on that Process Review fact.

If a future Scenario grants case-management authority while intentionally hiding some child resources, M3.3 returns an authorization-safe partial projection rather than leaking hidden aggregate facts.

## Progress model

M3.3 does not invent a generic percent-complete formula.

A percentage such as `73% complete` would require cross-Scenario semantics for weighting Cases, Findings and Actions that do not currently exist.

The first progress projection is therefore factual and count-based.

### ReviewCase facts

Each management Case summary exposes:

```text
id
review_plan_id
title
scenario_key
scenario_version
lifecycle
planned_start_at
planned_end_at
deadline_bucket
```

plus authorized Finding and Action lifecycle aggregates.

### Finding progress

For authorized Findings under the Case, M3.3 aggregates exact persisted lifecycle facts:

```text
total
open
rectifying
verifying
closed
voided
```

The progress detail exposes authorized Finding rows with persisted title, severity, lifecycle, and raised_at plus per-Finding Action counts.

M3.3 does not collapse Finding lifecycle into a new persisted `progress_status`.

### Action progress

For Actions belonging to authorized Findings, M3.3 aggregates exact persisted lifecycle facts:

```text
total
todo
in_progress
done
cancelled
overdue
due_soon
```

The progress detail also provides deterministically ordered overdue/due-soon Action deadline items.

## Deadline semantics

M3.3 reuses the deadline semantics frozen by M3.1.

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

For due-soon presentation M3.3 uses the same seven-day projection window:

```text
as_of <= deadline <= as_of + 7 days
```

This remains a read-model window only.

### No generic Finding deadline in M3.3

M3.1 intentionally deferred the question of a generic Finding deadline.

M3.3 does **not** establish enough cross-Scenario evidence to add one merely for dashboard convenience.

M3.3 does not derive a Finding deadline from:

- `scenario_data`;
- the earliest or latest Action `due_at`;
- ReviewCase `planned_end_at`;
- Submission timestamps; or
- any heuristic.

If a future Scenario proves that `Finding.due_at` is a real cross-Scenario business fact, that domain change requires a separate architecture review.

## Collection query

`GET /api/v1/management/review-cases` provides a bounded deterministic list of managed Case summaries.

The implemented filters are:

```text
review_plan_id
lifecycle
deadline_status = all | due_soon | overdue
limit
offset
```

Filters operate only inside the already-authorized management scope.

Each returned Case summary includes:

- Case identity, ScenarioVersion, and lifecycle;
- planned deadline facts and derived deadline bucket;
- Finding lifecycle counts for authorized Findings;
- Action lifecycle/deadline counts for authorized Findings.

The endpoint does not expose Notification state as management truth.

## Authorization-safe external pagination

External pagination is defined over the final authorized management collection, never over raw direct-CaseMember candidates.

The observable collection semantics are:

```text
direct CaseMember candidates
        ↓
organization-scoped persisted facts
        ↓
exact historical ScenarioVersion
        ↓
target-specific AuthorizationContext
        ↓
ScenarioPolicy.authorization.allows("manage_case_members", ...)
        +
ScenarioPolicy.authorization.allows("view_case", ...)
        ↓
AUTHORIZED MANAGEMENT SET
        ↓
authorized child projection
        ↓
requested filters
        ↓
deterministic ordering
        ↓
external limit / offset
        ↓
response
```

The implementation currently bulk-loads the relevant candidate/fact categories before authorization and slices only the final authorized/filtered/ordered summaries. Internal bounded candidate scanning remains a legal future optimization provided it preserves the same external semantics.

The following implementation shape remains forbidden:

```text
candidate SQL
    ↓
external LIMIT / OFFSET
    ↓
exact Scenario authorization
    ↓
discard unauthorized rows
```

An unauthorized candidate ReviewCase therefore:

- does not consume an external page position;
- does not reduce page fullness when enough later authorized Cases exist;
- does not enter the externally reported `total` value; and
- does not change the relative page placement of authorized Cases merely because hidden candidates are inserted or removed.

Acceptance uses an interleaved `A / H1 / B / H2 / C` shape and verifies `limit=2` yields page 1 `A,B` and page 2 `C`, including after another hidden candidate is inserted between visible Cases.

This is both a correctness and privacy boundary.

## Progress detail query

`GET /api/v1/management/review-cases/{case_id}/progress` returns a read-only drill-down for one managed Case.

It includes:

- the same Case summary facts;
- Finding-level progress rows for authorized Findings;
- per-Finding Action lifecycle counts;
- overdue and due-soon Action deadline items; and
- one captured `as_of` timestamp for all deadline calculations in the response.

The detail endpoint is organization + business-authorization scoped. Known foreign or unauthorized UUIDs return non-disclosing 404 behavior.

## Deterministic ordering

The collection order is:

1. overdue Cases first;
2. then non-overdue Cases by `planned_end_at`;
3. null deadlines after dated Cases; and
4. stable Case UUID as final tie-breaker.

Within progress detail:

- overdue Actions: oldest deadline first;
- due-soon Actions: nearest deadline first;
- Findings: `raised_at`, then stable id.

Ordering is a read-model concern only.

## Query implementation boundary

M3.3 lives in the dedicated read-side module:

```text
src/easyaudit_next/management/
    query_service.py
    schemas.py
    api.py
```

It reads SQLAlchemy persistence records directly and does not add management-only methods to `ReviewCoreRepository`.

Review Core does not import `management`, `workbench`, `notifications`, or `collaboration`; the architecture check now enforces the downstream dependency boundary.

M3.3 uses Scenario-neutral `AuthorizationContext`/`RoleGrant` facts and does not copy the Process Review role matrix into the management module.

## Query performance boundary

The collection endpoint avoids dashboard N+1 behavior by loading query categories in bulk:

```text
candidate Case memberships
Case rows
ScenarioVersion rows
Scenario rows
Finding rows
Action rows
caller-relevant FindingParticipant facts
caller-relevant ActionAssignee facts
```

When data exists this is category-bounded rather than per-Case/per-Finding/per-Action SQL.

A PostgreSQL query-count regression test compares 5 and 100 managed Cases, each with Finding/Action relationship facts. The SELECT count remains unchanged and is guarded by a small implementation-level upper bound rather than an exact public SQL contract.

M3.3 adds no migration or management indexes. Existing M3.1 reverse-lookup indexes and current parent/organization access paths support the implemented query categories; no redundant index was added merely to match the Gate sketch.

## Organization and privacy boundary

Every query is constrained by the authenticated user's `organization_id` before materialization.

The management API does not expose:

- another Organization's Cases;
- same-Organization Cases the caller is not authorized to manage;
- existence of a Case merely because its UUID is known;
- hidden Finding or Action counts;
- pagination gaps or totals caused by unauthorized candidate Cases;
- `system_admin` bypass data; or
- aggregate totals that include unauthorized resources.

Acceptance includes a known foreign ReviewPlan filter and known unauthorized Case UUIDs.

## Read-only side-effect boundary

Both M3.3 endpoints are GET/read-side operations. PostgreSQL/API Acceptance compares state before and after requests and proves:

- ReviewCase lifecycle is unchanged;
- Activity count is unchanged;
- Notification count/read state is unchanged; and
- no durable management business rows are created.

## No M3.4 behavior

M3.3 does not send, create, schedule, or retry reminders.

It does not add:

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

## Acceptance evidence

The implementation Acceptance suite uses real PostgreSQL and includes custom Scenario policies specifically designed to expose forbidden shortcuts.

It proves:

- exact historical ScenarioVersion management authorization (v1/v2 behavior differs);
- a custom non-`lead` `manage` role works only because the exact Scenario Policy allows it;
- interleaved hidden candidates do not consume external page positions or enter `total`;
- inserting a hidden candidate does not move authorized Cases between pages;
- sibling Finding/Action grants cannot broaden a target Finding's `view_finding` context;
- hidden Finding and hidden overdue Action facts never enter lifecycle/deadline aggregates;
- all Finding and Action lifecycle categories aggregate from persisted facts;
- Case and Action deadline boundaries at `as_of`, `as_of + 7 days`, null deadlines, and terminal states are correct;
- `review_plan_id`, `lifecycle`, and `deadline_status` filters operate inside authorization scope;
- a foreign ReviewPlan filter yields no disclosure;
- `system_admin` without Case business authority gets no implicit management visibility;
- known unauthorized/foreign Case UUIDs are non-disclosing;
- query count stays category-bounded from 5 to 100 Cases; and
- GET APIs append no Activity/Notification and change no Review lifecycle.

## CI evidence

Implementation head:

`f4aea0540abf33ea939cc640e8e1e0c220116b29`

CI #176 is fully green:

- Ruff: pass;
- mypy: `73 source files`, no issues;
- architecture check: pass;
- OpenAPI contract: pass;
- Alembic `0001 → 0010`: pass on PostgreSQL;
- pytest: **224 passed / 1 warning**.

The single warning is the existing Starlette/FastAPI TestClient deprecation warning about future `httpx2` migration and is unrelated to M3.3 semantics.

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

M3.3 implementation and Acceptance are complete when an authenticated user can query only the ReviewCases that the exact historical Scenario Policy authorizes them to manage, obtain factual Case/Finding/Action progress and overdue projections with no hidden-child leakage, paginate the final authorized management collection without hidden-candidate side channels, and do so with category-bounded PostgreSQL queries while Review Core, Notification semantics, and M3.4 reminder behavior remain unchanged.

The PR remains Draft and unmerged pending M3.3 Final Architecture Review.
