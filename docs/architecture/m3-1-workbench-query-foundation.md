# M3.1 — Workbench & Query Foundation

M3.1 is the first Collaboration & Management slice. It consumes the M2 Review Core as a stable write model and adds a user-centric read side without introducing a second task truth.

## Goal

Provide one authenticated query surface answering: **what work is relevant to me now?**

The initial API is:

```http
GET /api/v1/me/workbench
```

The response is an aggregate DTO, not a persisted business entity. It contains:

- direct ReviewCase responsibilities;
- Finding responsibilities;
- ActionItem responsibilities;
- Findings currently awaiting verification by the caller;
- due-soon ReviewCases and ActionItems; and
- overdue ReviewCases and ActionItems.

## Hard architecture boundary

M3.1 is read side only.

It must not:

- add `WorkItem`, `TodoTask`, `InboxTask`, `ManagementTask`, or equivalent persistence;
- mutate ReviewCase, Finding, ActionItem, membership, participant, assignee, Submission, or Activity state;
- change M2 lifecycle values, transition rules, concurrency guards, lock order, or Scenario contracts;
- give `system_admin` implicit business visibility;
- copy business authorization into a second workbench-specific role matrix; or
- infer resource visibility from UUID possession.

The workbench may add indexes required for reverse relationship lookups. Such indexes are query infrastructure only and do not change Review Core semantics.

## Source of truth

Workbench membership and authority are derived from the existing M2 facts:

```text
CaseMember
FindingParticipant
ActionAssignee
ReviewCase.scenario_key + scenario_version
ScenarioPolicy.authorization
```

Relationship rows are candidate facts, not final authorization decisions. A candidate item is returned only when the exact historical Scenario Policy permits the relevant capability for the current user.

For Process Review v1 this means, among other things, that a `verifying` Finding belongs in `verification_queue` only when the exact policy allows `verify_finding`; the query must not hard-code `role_key == reviewer` as the authorization truth.

## Responsibility semantics

### ReviewCase responsibilities

A ReviewCase responsibility is a direct CaseMember relationship for the current user. The DTO aggregates all direct CaseMember `role_key` values for the Case.

The Case is returned only if the exact Scenario Policy allows `view_case` for the derived authorization context.

### Finding responsibilities

A Finding responsibility is a FindingParticipant relationship through which the current user participates directly or, where a Scenario explicitly grants authority through department membership, through the user's primary department.

The DTO must preserve the source of the relationship (`direct` or `department_membership`) rather than pretending that department visibility is equivalent to explicit ownership.

The Finding is returned only if the exact Scenario Policy allows `view_finding`.

### ActionItem responsibilities

An ActionItem responsibility is an ActionAssignee relationship through which the current user participates directly or, where a Scenario explicitly grants it, through department membership.

The owning Finding and ReviewCase are included only as display context. The query does not create a new Action workflow or permission model.

## Verification queue

Candidate rows are Findings with:

```text
Finding.lifecycle = verifying
```

For every candidate, M3.1 resolves the parent ReviewCase's exact `(scenario_key, scenario_version)`, derives the current user's AuthorizationContext from persisted Case/Finding/Action relationships, and asks that Scenario Policy whether `verify_finding` is allowed.

Only authorized Findings are returned.

This preserves the M2 rule that platform administration and business verification authority are separate.

## Deadline projection

M3.1 does not invent new deadline semantics.

The current M2 model has:

```text
ReviewCase.planned_end_at
ActionItem.due_at
```

but no generic `Finding.due_at`.

Therefore the M3.1 deadline buckets contain only ReviewCases and ActionItems.

A Finding-level due date must not be added merely to satisfy the Workbench. If M3.3 later proves that a generic Finding deadline is a real cross-Scenario requirement, that decision must be reviewed independently.

### Overdue

At query time `as_of`:

```text
ReviewCase overdue
= planned_end_at < as_of
  AND lifecycle in {scheduled, in_progress}

ActionItem overdue
= due_at < as_of
  AND lifecycle in {todo, in_progress}
```

Terminal states are excluded.

### Due soon

M3.1 uses a presentation window of seven days:

```text
as_of <= deadline <= as_of + 7 days
```

using the same eligible lifecycle sets as the overdue rules.

This seven-day window is a Workbench projection rule only. It is not the M3.4 reminder cadence and does not create Notification or Scheduler behavior.

## Query implementation boundary

M3.1 should introduce a dedicated module:

```text
src/easyaudit_next/workbench/
    query_service.py
    schemas.py
    api.py
```

The query layer may read persistence models directly or through a dedicated read repository. It must not expand `ReviewCoreRepository` merely to support product projections.

The implementation should avoid the existing per-aggregate authorization helpers becoming an N+1 query loop across dozens of resources. Candidate relationship facts should be fetched in bulk, grouped in memory, and then evaluated with the exact Scenario Policy.

## Required reverse-lookup indexes

The M2 write model is primarily indexed from aggregate parent to child. Workbench queries also need user-to-work reverse lookup.

M3.1 may add indexes such as:

```text
case_members(organization_id, user_id, case_id)
finding_participants(organization_id, user_id, finding_id) WHERE user_id IS NOT NULL
finding_participants(organization_id, department_id, finding_id) WHERE department_id IS NOT NULL
action_assignees(organization_id, user_id, action_item_id) WHERE user_id IS NOT NULL
action_assignees(organization_id, department_id, action_item_id) WHERE department_id IS NOT NULL
findings(organization_id, lifecycle, case_id)
action_items(organization_id, due_at, lifecycle)
```

Exact index shapes may be adjusted after PostgreSQL query-plan tests, but M3.1 must not solve read performance by denormalizing a second responsibility table.

## API privacy contract

`GET /api/v1/me/workbench` is organization-scoped from the authenticated identity and returns only authorized resources.

The API must not expose:

- counts of unauthorized sibling resources;
- existence of another organization's resource IDs;
- hidden Case/Finding aggregate facts used during policy evaluation; or
- any special `system_admin` bypass.

An active business identity is required, consistent with the existing Review APIs.

## Ordering

The first version uses deterministic ordering:

- overdue: oldest deadline first;
- due soon: nearest deadline first;
- verification queue: oldest `raised_at` first;
- responsibilities: deadline first when present, then stable resource ID.

Ordering is a read-model concern and does not affect domain state.

## End state

M3.1 is complete when one authenticated user can retrieve a single Workbench snapshot that correctly projects their M2 relationships and Scenario authorization across Cases, Findings, and Actions, while Review Core remains semantically unchanged.
