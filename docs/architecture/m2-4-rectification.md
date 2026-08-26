# M2.4 — Rectification

## Scope

M2.4 implements the generic Review Core application path for rectifying an issued Finding:

- create, list, and get ActionItem;
- add and list typed ActionAssignee relationships;
- transition ActionItem lifecycle through the exact Case ScenarioVersion;
- register and list immutable Evidence metadata anchored to an ActionItem;
- create formal rectification plan and completion Submission snapshots; and
- atomically advance a Finding from `rectifying` to `verifying` when the Scenario accepts a
  completion Submission.

M2.4 does not implement verification approve/reject, Finding reopen, or ReviewCase closure. Those
remain M2.5 scope. It also does not expose ordinary ActionItem lifecycle PATCH/delete, Evidence
mutation/delete, or Submission mutation/delete.

## Scenario operation boundary

M2.4 extends the same boundary established by M2.3:

```text
read ReviewCase / Finding / ActionItem / relationships
                  ↓
assemble Scenario-neutral operation facts
                  ↓
policy.action_operations.validate_*
policy.action_workflow.transition / submission_policy.decide
                  ↓
Scenario decides whether the business operation is valid
                  ↓
Review Core performs generic persistence / concurrency coordination / CAS / Activity
```

`ActionItemOperationContext` is a Scenario-neutral fact carrier containing:

- parent ReviewCase lifecycle;
- parent Finding lifecycle;
- current ActionItem lifecycle, when applicable;
- persisted ActionAssignee role presence; and
- an operation reason when supplied.

`ScenarioPolicy` requires an `action_operations` capability. Review Core therefore does not need a
Process Review branch to decide when Action creation, assignment, lifecycle transition, or Evidence
registration is legal.

Process Review v1 currently freezes these rectification invariants:

- rectification operations require a parent Case in `in_progress` or `awaiting_closure`;
- the parent Finding must be `rectifying`;
- ActionItem creation starts at `todo` and cannot accept lifecycle from the client;
- ordinary ActionAssignee changes are limited to `todo` and `in_progress` Actions;
- `done` and `cancelled` Actions freeze ordinary assignee changes;
- Evidence may be registered for `todo`, `in_progress`, or `done` Actions, but not cancelled Actions;
- Action lifecycle calculation remains owned by `action_workflow`; and
- formal completion Submission remains owned by `submission_policy` and the Finding workflow.

The `awaiting_closure` allowance is intentional. Finishing fieldwork prevents discovering new
Findings, but an already-issued Finding may continue its rectification work before the Case can be
closed.

## Repository and authorization boundary

M2.4 does not expand every prior Review Core consumer to depend on rectification queries.
`ReviewCoreRepository` retains the pre-M2.4 core persistence contract, while
`RectificationRepository` extends it only with the aggregate capabilities required by this slice:
Action listing/CAS, ActionAssignee listing, Evidence, Finding Submission history, and the
Finding-level rectification concurrency guard.

The concurrency capability is deliberately placed on the M2.4 extension contract:

```text
lock_finding_for_rectification(organization_id, finding_id)
```

Its PostgreSQL implementation takes a row lock on the parent Finding:

```sql
SELECT ...
FROM findings
WHERE organization_id = :organization_id
  AND id = :finding_id
FOR UPDATE
```

The base `ReviewCoreRepository` therefore remains free of rectification-specific coordination.

The same separation exists in authorization. The base authorization context derives Case and
Finding relationship grants. M2.4 services explicitly build a rectification authorization context
that additionally derives ActionAssignee grants. Composition injects this action-aware behavior
into the current Planning, Finding, and Rectification application services without forcing older
Core services or test doubles to understand Evidence or Action aggregation.

For Process Review v1:

- Finding `owner` may create ActionItems and manage ActionAssignees;
- direct Action `primary` and `collaborator` Users may update their assigned Action and register
  Evidence;
- Finding `owner` may register Evidence and submit rectification;
- ActionAssignee relationships contribute visibility to their parent Finding/Case; and
- Department responsibility remains visibility-only and does not become Action write authority.

Actor-role combinations continue to be validated through versioned RoleSpecification. Process
Review v1 Action roles are User-direct relationships; a Department cannot be smuggled into a
`primary` or `collaborator` Action role.

A rectification Submission checks `view_finding` before it reads the decisive Action aggregate or
asks the Scenario to validate completion. A same-organization user with only a guessed Finding UUID
therefore receives authorization failure before lifecycle/Action-state validation can disclose
business state. The Scenario-required submit permission is still checked after the Scenario returns
the concrete SubmissionDecision.

## Real Action facts in Finding operations

M2.3 reserved `FindingOperationContext.non_cancelled_action_count` and
`all_non_cancelled_actions_done` for the later rectification stage. M2.4 now populates them from
persisted ActionItems rather than defaults.

For an existing Finding, Review Core reads all Actions, excludes `cancelled`, and supplies:

```text
non_cancelled_action_count = len(non_cancelled_actions)
all_non_cancelled_actions_done =
    non_cancelled_action_count > 0
    AND every non-cancelled Action lifecycle == done
```

The same persisted Action summary is supplied to a completion `SubmissionRequest`. Process Review
therefore cannot enter verification with zero non-cancelled Actions or while any non-cancelled
Action remains unfinished.

For completion, these decisive Action facts are read only after the parent Finding concurrency
guard has been acquired. Child rectification mutations use the same guard, so the Action set and
Action lifecycle facts cannot change concurrently across the `rectifying -> verifying` cutover.

## Rectification aggregate concurrency guard

`Finding` is the shared concurrency guard for the M2.4 rectification aggregate. Every write whose
legality depends on the parent Finding still being `rectifying` acquires the same Finding row lock
before reading the decisive mutable facts or persisting the child mutation:

- create ActionItem;
- manage ActionAssignee;
- transition ActionItem;
- register Evidence;
- submit rectification plan; and
- submit rectification completion.

The lock order is fixed as:

```text
Finding
   ↓
Action / ActionAssignee / Evidence / Submission
```

No M2.4 path first locks a child rectification row and then attempts to acquire the parent Finding
lock. This gives later extensions one explicit lock-order topology instead of allowing inverted
parent/child locking.

Callers first retain the lifecycle they observed before the guard. After `FOR UPDATE` returns, the
locked Finding is refreshed from PostgreSQL. If its lifecycle no longer matches that expected
snapshot, the request is treated as a concurrency conflict (`Concurrent Finding transition`, HTTP
409), not as an ordinary Scenario validation failure.

SQLAlchemy's identity map is explicitly accounted for. The `FOR UPDATE` query and decisive
post-lock Action reads use `populate_existing=True`, so a transaction that waited behind another
writer does not continue with pre-lock cached ORM lifecycle values.

For Action transitions, the originally observed Action lifecycle remains the expected value for the
Action CAS. The parent Finding guard therefore serializes cross-aggregate cutover, while the Action
CAS still detects Action-vs-Action competition. These mechanisms are complementary rather than
replacements for one another.

## Evidence and formal Submission

Migration `20260826_0008` adds `action_items.completed_at` and the `evidences` table. Evidence is
stored as immutable metadata referencing external/blob storage through `storage_key`; the Review
Core record contains the original name, media type, byte size, lowercase SHA-256 digest,
description, uploader, and creation time.

Evidence has organization-safe foreign keys to its ActionItem and uploader. PostgreSQL rejects
UPDATE or DELETE through an append-only trigger. M2.4 also activates the same database-level
append-only guarantee for formal `submissions`, whose domain model has been an immutable snapshot
since M1.

The API registers Evidence metadata but does not expose an Evidence update/delete route. Actual
binary object-storage transport is deliberately outside the Review Core domain contract; the
immutable record identifies and hashes the stored object.

## Action lifecycle concurrency

ActionItem lifecycle changes retain PostgreSQL compare-and-swap:

```text
UPDATE action_items
SET lifecycle = :target,
    completed_at = :completed_at
WHERE organization_id = :organization_id
  AND id = :action_item_id
  AND lifecycle = :expected_lifecycle
```

No matching row raises `Concurrent ActionItem transition`, mapped to HTTP 409, and no transition
Activity is written by the losing transaction. A PostgreSQL double-Session test still proves that
two callers reading the same old Action lifecycle produce one success, one Action CAS conflict, and
one transition Activity even after the parent Finding guard was introduced.

## Completion Submission atomicity and cutover

A rectification completion request is not a standalone Finding transition. Review Core:

1. resolves the Finding and authorization context and requires `view_finding`;
2. acquires the parent Finding rectification guard and verifies the locked lifecycle still matches
   the request snapshot;
3. reads refreshed persisted non-cancelled Actions under that guard;
4. asks the exact ScenarioVersion `submission_policy` for a `SubmissionDecision`;
5. authorizes the Scenario-required permission;
6. CAS-updates the Finding from `rectifying` to `verifying` when required;
7. inserts the immutable rectification Submission; and
8. appends its Submission-target Activity.

All writes use the request-scoped database transaction. PostgreSQL integration coverage proves:

- two concurrent Action transitions from the same old Action lifecycle still yield one success and
  one Action CAS conflict;
- two concurrent completion requests still yield one success and one Finding concurrency conflict,
  with only one completion Submission and one `finding.submitted_for_verification` Activity;
- completion racing `DONE -> reopen` can never persist `Finding=verifying` with
  `Action=in_progress`: completion wins and reopen conflicts, or reopen wins and completion rereads
  the unfinished Action and is rejected;
- completion racing Action creation can never persist `Finding=verifying` with a newly created
  `todo` Action: completion wins and creation conflicts, or creation wins and completion rereads the
  new unfinished Action and is rejected; and
- if Submission persistence fails after the Finding CAS has flushed, the whole transaction rolls
  back, leaving the Finding `rectifying` with no partial formal Submission.

The resulting invariant is stronger than transaction-local atomicity: `verifying` means both a
valid formal completion snapshot exists and the rectification Action aggregate was stable and fully
done at the cutover point.

## API error semantics

M2.4 follows the established API contract:

- authorization failure: 403;
- organization-scoped lookup miss: 404;
- Scenario operation/workflow/submission or request validation failure: 422;
- Action/Finding concurrency conflict: 409; and
- PostgreSQL uniqueness/integrity conflict: 409.

Parent Finding guard conflicts are mapped to the same 409 concurrency contract for Action create,
assignee management, Action transition, Evidence registration, and rectification Submission.
Lifecycle remains command-driven. Action lifecycle cannot be supplied on create or changed by an
ordinary PATCH, and Finding progression to `verifying` is available only through the formal
rectification Submission path.
