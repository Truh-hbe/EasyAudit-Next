# M3.1 Acceptance Gate

M3.1 is ready for Final Architecture Review only when CI proves all of the following.

## Architecture boundary

- Workbench is a pure projection; no WorkItem/TodoTask/InboxTask-style persistence exists.
- Review Core lifecycle values, transition semantics, Scenario contracts, concurrency guards, and lock order are unchanged from M2.
- `ReviewCoreRepository` is not expanded with Workbench-only query methods.
- Workbench query code is isolated under a dedicated read-side module.
- Any schema migration contains indexes only; it does not add business columns or entities.
- `system_admin` receives no implicit business visibility.

## API contract

- `GET /api/v1/me/workbench` requires the existing business identity dependency.
- The response is one aggregate DTO with `as_of`, Case responsibilities, Finding responsibilities, Action responsibilities, verification queue, due-soon buckets, and overdue buckets.
- OpenAPI documents the endpoint and all response models.
- The endpoint performs no business writes and appends no Activity.

## Organization scope and privacy

- Every Workbench query is constrained by `identity.user.organization_id` before result materialization.
- Cross-organization membership, participant, assignee, Case, Finding, and Action rows never appear.
- An unrelated same-organization user does not receive a resource merely because its ID is known.
- Unauthorized sibling/resource counts are not exposed.

## Scenario authorization

- Candidate relationship rows do not bypass the exact historical Scenario Policy.
- Case responsibilities are returned only when `view_case` is allowed.
- Finding responsibilities are returned only when `view_finding` is allowed.
- Verification queue contains only `Finding.lifecycle=verifying` items for which the exact Scenario Policy allows `verify_finding`.
- Verification selection is not implemented as `role_key == reviewer`.
- Platform administrator status is absent from the Workbench authorization decision.
- Existing `AuthorizationContext`, RoleGrant actor kind, and permission source semantics are preserved.

## Relationship semantics

- Direct CaseMember roles for one Case are aggregated without duplicate Case rows.
- Direct FindingParticipant and ActionAssignee relationships are aggregated without duplicate resources.
- Department-derived relationship facts remain distinguishable from direct-user relationships.
- A department relationship that grants only visibility is not presented as an explicit user ownership role.

## Deadline projection

At one captured timezone-aware `as_of` value:

```text
ReviewCase overdue
= planned_end_at < as_of
  AND lifecycle in {scheduled, in_progress}

ActionItem overdue
= due_at < as_of
  AND lifecycle in {todo, in_progress}

Due soon
= as_of <= deadline <= as_of + 7 days
  AND the same eligible lifecycle rules
```

CI must prove:

- overdue Case inclusion and terminal/non-active Case exclusion;
- overdue Action inclusion and done/cancelled exclusion;
- exact boundary behavior for `deadline == as_of` and `deadline == as_of + 7 days`;
- null deadlines are absent from deadline buckets; and
- no Finding deadline is synthesized from `scenario_data`, Action deadlines, or other heuristics.

## Query performance foundation

- M3.1 adds reverse-lookup indexes required for user/department Workbench queries.
- PostgreSQL integration tests inspect or exercise the candidate queries against real PostgreSQL.
- Workbench does not call per-resource repository helpers in an N+1 loop for every Case/Finding/Action.
- Candidate relationship facts are fetched in bulk and grouped before Scenario authorization evaluation.
- Query count is bounded by query category rather than linearly increasing with the number of returned resources.

## Deterministic ordering

CI proves deterministic ordering for:

- overdue: oldest deadline first;
- due soon: nearest deadline first;
- verification queue: oldest Finding `raised_at` first; and
- responsibility buckets: deadline first where present, then stable resource ID.

## Regression gate

- All M1 and M2 tests remain green, including the 189-test M2 regression baseline.
- Existing Process Review E2E remains unchanged in meaning.
- Existing PostgreSQL concurrency tests remain green.
- Ruff, mypy, architecture checks, OpenAPI checks, and Alembic migration checks remain green.

## M3.1 end-to-end proof

A PostgreSQL integration/API test must create at least two organizations and multiple same-organization users, then prove one user's Workbench snapshot across this shape:

```text
Case A: caller is lead
Case B: caller is observer
Case C: caller has no CaseMember role but is Finding owner
Case D: caller is Action primary assignee
Case E: verifying Finding and caller is Scenario-authorized verifier
Case F: verifying Finding but caller is not authorized verifier
Case G: other organization
```

The response must include only the resources justified by the current user's relationships and exact Scenario authorization, place Case/Action deadlines into the correct due buckets, and expose no data from Case F/G beyond what the caller is otherwise authorized to see.

The PR remains Draft and unmerged after this gate. M3.1 Final Architecture Review begins only after implementation and CI satisfy this document.
