# M3.4 — Reminder / Nudge Architecture Gate

M3.4 is the fourth Collaboration & Management slice. It builds on merged M3.2 persistent Notifications and merged M3.3 management/deadline projections.

This first Gate is **design-only**. It freezes reminder/nudge semantics, recipient resolution, Activity provenance, Notification idempotency/deduplication, and the boundary between manual nudge and automatic reminder.

It does **not** implement a scheduler, cron loop, worker, background scan, reminder cadence, escalation, snooze, external delivery, or frontend behavior.

## Goal

M3.4 adds one collaboration capability:

> **An authorized manager may explicitly nudge currently responsible users, and a future automatic reminder mechanism may notify currently responsible users when an existing persisted deadline satisfies an approved reminder policy — without changing Review Core workflow truth.**

The slice must preserve these foundations:

```text
ReviewCase / CaseMember
Finding / FindingParticipant
ActionItem / ActionAssignee
Submission
Activity
ScenarioPolicy.authorization
Notification
```

M3.4 does not add a second task truth and does not create a Reminder lifecycle aggregate.

## Terminology

### Manual nudge

A **manual nudge** is an explicit human action initiated by an authenticated user.

It means:

> "I am authorized to manage this work and I am deliberately asking the currently responsible person(s) to act."

A manual nudge:

- is not dependent on the subject being due soon or overdue;
- is not a lifecycle transition;
- does not modify Case/Finding/Action responsibility;
- does not grant authorization;
- is an auditable user action; and
- may create one Notification per resolved concrete recipient.

### Automatic reminder

An **automatic reminder** is a policy-driven delivery caused by current persisted business facts plus time.

It means:

> "At this evaluation instant, this existing deadline satisfies an approved reminder condition, so the currently responsible user(s) should be notified."

An automatic reminder:

- has no human initiator;
- must never impersonate a User actor;
- is not a Review Core lifecycle event;
- does not create or change business responsibility;
- must be safe under repeated evaluation; and
- is implemented only after a later Implementation Gate explicitly introduces execution infrastructure.

## Hard boundary: no Reminder business aggregate

M3.4 does not introduce:

```text
Reminder.status
Reminder.lifecycle
ReminderTask
NudgeTask
SupervisionTask
EscalationCase
ReminderAssignment
```

or any equivalent second workflow truth.

A reminder/nudge is a collaboration delivery behavior over existing Review Core facts.

Notification history may prove that a user was notified. It does not prove that the user still owns the work, that the work is still overdue, or that a management action is still pending.

## First-slice subject scope

### Manual nudge subjects

The first M3.4 manual action is intentionally limited to:

```text
Finding
ActionItem
```

ReviewCase-level manual nudge is deferred because a generic Case does not yet have a cross-Scenario notion of "the person who should be chased" distinct from management authority.

### Automatic reminder subjects

Automatic deadline semantics are limited to persisted deadlines already accepted by M3.1/M3.3:

```text
ReviewCase.planned_end_at
ActionItem.due_at
```

No automatic Finding deadline reminder exists in M3.4 because Review Core has no generic `Finding.due_at`.

M3.4 must not derive a Finding deadline from:

- Scenario JSON;
- ReviewCase planned end;
- earliest/latest Action deadline;
- Submission timestamps; or
- any heuristic.

## Deadline eligibility is not cadence

M3.4 reuses the factual deadline predicates already frozen by M3.3:

```text
ReviewCase overdue
= planned_end_at < as_of
  AND lifecycle in {scheduled, in_progress}

ActionItem overdue
= due_at < as_of
  AND lifecycle in {todo, in_progress}
```

The existing seven-day `due_soon` window remains a **read-model projection**. This Gate does not silently convert it into a notification cadence.

This first Gate does not decide:

- how many days before due date to send;
- whether overdue reminders repeat daily/weekly;
- maximum reminder count;
- escalation thresholds;
- quiet hours;
- snooze; or
- user preferences.

Those are policy/cadence decisions for the later Implementation Gate.

## Manual nudge sender authorization

A manual nudge is a management write-side collaboration action, but it does not become a Review Core mutation.

The caller must already be inside the existing M3.3 management scope for the parent ReviewCase:

1. active authenticated BusinessIdentity in the same Organization;
2. direct CaseMember relationship on the parent ReviewCase;
3. exact persisted ScenarioVersion allows `manage_case_members` for the target Case context; and
4. exact persisted ScenarioVersion allows `view_case`.

For a Finding or ActionItem target, the caller must additionally pass exact target-specific `view_finding` authorization for the parent Finding before any target details or recipient facts are disclosed.

This deliberately reuses the already-approved Scenario-owned management capability rather than hard-coding `lead`, inventing a platform `manager`, or granting `system_admin` a business bypass.

If a future Scenario needs a user who may nudge without `manage_case_members`, that is a separate Scenario-contract review.

## Manual recipient resolution

The client does **not** send arbitrary recipient User IDs in the first slice.

Recipients are resolved from current business responsibility using the exact historical Scenario Policy and target-specific AuthorizationContext.

### Finding nudge recipients

For a Finding nudge, candidate active users are evaluated for:

```text
ScenarioPolicy.authorization.allows(
    "submit_rectification",
    target_specific_finding_context,
)
```

This intentionally identifies users with current formal responsibility to submit rectification under that Scenario without comparing role names such as `owner`.

For `process_review@1`, the current policy means the direct Finding owner qualifies. M3.4 code must not know that fact.

### ActionItem nudge recipients

For an ActionItem nudge, candidate active users are evaluated for:

```text
ScenarioPolicy.authorization.allows(
    "update_assigned_action",
    target_specific_action_context,
)
```

For `process_review@1`, current primary/collaborator assignees qualify through the Scenario Policy. M3.4 code must not compare those role keys.

### Recipient snapshot

Recipient resolution occurs at nudge/reminder creation time:

```text
current business relationships at T0
        ↓
active same-Organization candidate users at T0
        ↓
exact target-specific Scenario authorization at T0
        ↓
concrete User Notification rows
```

Later assignment, department, or authorization changes do not rewrite historical Notification recipients.

The sender is excluded from their own manual nudge delivery even if they also satisfy the target responsibility permission.

If no eligible recipient exists, a manual nudge fails as a business validation error and creates neither Activity nor Notification.

## Automatic recipient resolution

Automatic reminders resolve **current** responsible users at the evaluation instant; they do not replay recipients from an older assignment event.

### ReviewCase automatic reminder

Candidates are active users evaluated against the exact persisted ScenarioVersion for:

```text
ScenarioPolicy.authorization.allows(
    "transition_case",
    target_specific_case_context,
)
```

This identifies the user(s) currently responsible for driving the Case lifecycle without hard-coding `lead`.

### ActionItem automatic reminder

Candidates are active users evaluated for:

```text
ScenarioPolicy.authorization.allows(
    "update_assigned_action",
    target_specific_action_context,
)
```

No platform role is a recipient shortcut. `system_admin` receives no automatic reminder unless the exact Scenario business authorization independently qualifies that user.

## Target-specific authorization remains mandatory

Bulk recipient discovery is allowed for query efficiency, but grants must be grouped by target before Scenario authorization.

The forbidden shape remains:

```text
load all same-Case grants
        ↓
put them in one AuthorizationContext
        ↓
authorize every sibling Finding/Action
```

A role on Finding/Action A must not cause a nudge/reminder for sibling B.

Custom Scenario Acceptance must be able to expose both hard-coded role shortcuts and sibling-grant leakage.

## Manual nudge Activity provenance

A manual nudge is an auditable human collaboration action and therefore creates exactly one append-only Activity for the target subject.

The intended event vocabulary is:

```text
finding.nudged
action_item.nudged
```

Exact naming may be refined before implementation, but the semantic requirements are fixed:

- subject is the exact Finding or ActionItem;
- `actor_id` is the authenticated sender;
- Activity is append-only;
- no Review lifecycle changes; and
- all Notifications created by that nudge reference the exact Activity ID created for that same manual action.

The required provenance chain is:

```text
manual nudge authorization
        ↓
resolve current recipients
        ↓
append exact Activity N
        ↓
create Notification rows
        ↓
Notification.origin_activity_id = ActivityId(N)
        ↓
commit one request transaction
```

The Activity ID must be propagated directly in memory from the append operation. M3.4 must not recover it using:

- latest Activity lookup;
- subject + event_type lookup;
- timestamp matching;
- Activity history scanning; or
- any other provenance inference.

Notification persistence failure must roll back the manual nudge Activity in the same request transaction.

A successful manual nudge must not call any Review Core lifecycle transition service.

## Automatic reminders must not fabricate Review Activity

An automatic reminder is a delivery policy evaluation, not a new Review Core business mutation.

Therefore the automatic path must **not** create a fake Review Activity solely to satisfy the current M3.2 `origin_activity_id` schema.

This is a deliberate evolution of the M3.2 model:

- existing event-backed Notifications remain exactly Activity-backed;
- manual nudges are also Activity-backed because a human nudge is itself an auditable action;
- automatic reminders require a non-Activity provenance/idempotency origin owned by the collaboration/reminder slice.

The later implementation may evolve Notification persistence to represent a typed origin such as:

```text
ActivityOrigin(activity_id)
OR
AutomaticReminderOrigin(stable_reminder_key)
```

with an exactly-one-origin invariant, or an equivalent schema with the same semantics.

What is forbidden is generating synthetic Review Activity rows merely so automatic Notification inserts can reuse the old non-null column.

Automatic reminder history is already represented by immutable Notification delivery rows. It must not flood the Review Activity timeline with repeated timer executions.

## Notification kinds

M3.4 must keep manual and automatic deliveries distinguishable.

The first semantic catalog is:

```text
manual_finding_nudge
manual_action_nudge
automatic_case_reminder
automatic_action_reminder
```

Exact enum spelling may be refined before implementation, but a manual nudge and an automatic reminder must never share one ambiguous kind.

## Idempotency and deduplication

### Existing event-backed Notifications

M3.2 semantics remain unchanged:

```text
organization
+ recipient
+ exact origin Activity
+ notification kind
```

identifies one logical event-backed delivery.

### Manual nudge Notifications

One successful manual nudge Activity may fan out to multiple users, but each concrete recipient receives at most one Notification for that Activity/kind.

The existing Activity-backed uniqueness invariant therefore remains sufficient for recipient fan-out dedupe inside one manual nudge occurrence.

Two deliberately separate manual nudge actions are distinct occurrences and may legitimately produce two Activities and two Notifications.

This Gate does not introduce a generic HTTP idempotency-key framework for suppressing separate intentional nudge actions.

### Automatic reminder Notifications

Automatic execution may evaluate the same logical reminder repeatedly. Deduplication therefore cannot depend on an Activity ID or on `SELECT before INSERT`.

The automatic reminder path must have a stable logical occurrence key supplied by the reminder policy/execution design.

The invariant must be equivalent to:

```text
organization
+ recipient
+ notification kind
+ typed subject
+ reminder policy occurrence key
```

The occurrence key must remain stable across:

- process restarts;
- repeated scans;
- concurrent workers;
- transaction retry; and
- duplicate candidate discovery.

A distinct legitimate reminder occurrence must receive a different occurrence key.

For deadline-driven reminders, the logical identity must bind to the deadline fact being evaluated so that changing `planned_end_at` or `due_at` cannot cause an old dedupe key to suppress a reminder for the new deadline.

Database uniqueness/atomic conflict handling is mandatory. Title/body matching and race-prone `SELECT before INSERT` are forbidden.

The exact cadence component of the occurrence key is deferred until cadence itself is reviewed into scope.

## Transaction boundaries

### Manual nudge

The manual nudge Activity and required in-app Notification rows commit atomically in one request transaction.

```text
Activity + Notification(s)
        ↓
one commit
```

No Review Core entity is mutated.

### Automatic reminder

The future automatic execution transaction persists only collaboration/reminder delivery facts required by the approved design.

It does not hold a Review Core lifecycle lock merely because a deadline was read, and it does not perform a lifecycle transition.

Before persistence, the execution path must re-evaluate the current target state/deadline sufficiently to avoid delivering based on a stale terminal target.

The detailed scheduler transaction/locking strategy is deliberately outside this first Gate.

## API boundary for the later implementation

The manual action is expected to become an authenticated command endpoint with a narrow shape such as:

```http
POST /api/v1/findings/{finding_id}/nudge
POST /api/v1/action-items/{action_item_id}/nudge
```

The client does not choose arbitrary recipients and does not submit lifecycle fields.

Known unauthorized or foreign target UUIDs must preserve the existing non-disclosing resource behavior.

Exact request/response DTOs are deferred until the Implementation Gate.

No automatic reminder endpoint is required; automatic execution is not an HTTP business mutation.

## Dependency boundary

The intended dependency direction is:

```text
Review Core persisted facts / Scenario-neutral authorization contracts
        ↓
collaboration reminder/nudge orchestration
        ↓
Notification persistence
```

For manual nudge only, collaboration also appends a generic typed Activity fact without changing Review Core lifecycle.

Review Core domain/application and Scenario implementations must not import:

```text
notifications
collaboration
management
scheduler
reminder/nudge modules
```

M3.4 must not add nudge/reminder methods to the base `ReviewCoreRepository`.

Dedicated collaboration query/write helpers are allowed.

## Explicitly out of scope for this first Gate

This first M3.4 Gate does not implement or freeze:

- scheduler process/entrypoint;
- cron configuration;
- background scanning loop;
- reminder cadence;
- escalation;
- snooze;
- quiet hours;
- user notification preferences;
- email/webhook/IM/SMS/push delivery;
- ReviewCase manual nudge;
- Finding automatic deadline reminders;
- a generic `Finding.due_at`;
- notification templates or template DSL;
- a Reminder domain lifecycle/entity;
- management write-state entities;
- second Scenario production implementation; or
- frontend UI.

## End state of this Gate

This architecture Gate is complete when review accepts these invariants:

1. manual nudge and automatic reminder are distinct semantics;
2. manual nudge is an auditable human Activity with exact provenance;
3. automatic reminder is delivery-policy behavior and must not fabricate Review Activity;
4. recipients are concrete active users resolved from current exact Scenario authorization, never hard-coded role names;
5. target-specific authorization prevents sibling grant leakage;
6. M3.2 event Notification provenance remains intact;
7. manual and automatic Notification dedupe have stable database-enforced logical identities;
8. no Finding deadline is invented;
9. no scheduler/cadence implementation enters this first PR; and
10. M2/M3.1/M3.2/M3.3 lifecycle, authorization, concurrency, Workbench, Notification inbox, and management read semantics remain unchanged.
