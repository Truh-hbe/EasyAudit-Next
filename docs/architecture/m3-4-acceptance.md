# M3.4 Acceptance Gate — Reminder / Nudge

This document is the first M3.4 Architecture & Acceptance Gate. It freezes required semantics before any scheduler or reminder execution implementation is allowed.

The PR that introduces this Gate remains **Draft / open / unmerged**. No scheduler, cron, worker, background scan, cadence, escalation, snooze, or external delivery implementation may enter this first design PR.

M3.4 is ready for Implementation Gate only after architecture review explicitly accepts this contract.

## Baseline

M3.4 starts from merged M3.3 on:

```text
main@1b3146172e75371f79352e115229031a71c7a99d
```

The implementation must preserve all M2, M3.1, M3.2, and M3.3 semantics unless this document explicitly evolves one collaboration contract.

The one intentional future persistence evolution is that automatic reminder Notifications cannot be forced to invent Review Activity provenance solely because M3.2 currently requires non-null `origin_activity_id`.

## Architecture boundary

Acceptance must prove:

- no `Reminder`, `NudgeTask`, `SupervisionTask`, `ReminderStatus`, or equivalent second workflow truth is introduced;
- no ReviewCase/Finding/ActionItem lifecycle state or transition is added or modified;
- no Submission rule or M2 concurrency/lock protocol is changed;
- no generic Finding deadline is added;
- Review Core domain/application and Scenario implementations do not import collaboration/reminder/notification/scheduler modules;
- no reminder/nudge methods are added to the base `ReviewCoreRepository`;
- `system_admin` receives no implicit business nudge authority and no implicit reminder delivery;
- Notification does not become an authorization source; and
- Workbench/Management remain current-state read projections rather than reminder truth.

## First-Gate scope proof

The first design PR must contain only Gate/documentation changes required to freeze this contract.

It must not add:

- scheduler source files;
- scheduler process entrypoints;
- cron configuration;
- background workers;
- new reminder migrations;
- new Notification kinds in executable code;
- nudge HTTP routes;
- timer/background tests; or
- frontend reminder/nudge UI.

A diff outside the Gate documentation requires explicit review before this first PR can remain in scope.

## Manual nudge semantics

The later implementation must support manual nudge only for:

```text
Finding
ActionItem
```

A manual nudge:

- is explicitly initiated by an authenticated human;
- may occur whether or not the target is due soon/overdue;
- changes no Review Core lifecycle or responsibility relationship;
- creates exactly one append-only Activity for one successful logical nudge occurrence;
- creates zero or more user-specific Notification rows only after recipient resolution succeeds; and
- never accepts arbitrary client-selected recipient IDs in the first slice.

ReviewCase manual nudge remains out of scope.

## Manual sender authorization

PostgreSQL/API Acceptance must prove that the sender:

1. is an active same-Organization BusinessIdentity;
2. has a direct CaseMember relationship on the parent ReviewCase;
3. is allowed `manage_case_members` by the exact persisted historical ScenarioVersion for the target Case;
4. is allowed `view_case`; and
5. is allowed target-specific `view_finding` before a Finding/Action target can be nudged.

Required negative cases:

- observer-only or otherwise non-managing Case member cannot nudge;
- unrelated same-Organization user cannot nudge;
- `system_admin` without Scenario business authority cannot nudge;
- cross-Organization identity cannot nudge;
- known unauthorized/foreign UUIDs preserve non-disclosing behavior; and
- sibling Finding/Action grants cannot broaden sender authorization for the target.

A custom Scenario must prove M3.4 does not compare `role_key == "lead"` or use Process Review role names as sender authorization.

## Manual Finding recipient resolution

For one target Finding, each active candidate user must be evaluated with the exact historical Scenario Policy and target-specific context for:

```text
submit_rectification
```

Acceptance must prove:

- Process Review v1 currently resolves its legitimate rectification submitter(s) without role-name comparisons;
- a same-Organization user who can view the Finding but cannot submit rectification does not receive the nudge;
- `system_admin` without exact Scenario authority does not receive it;
- another Organization never receives it;
- the sender is excluded from self-delivery; and
- a custom Scenario with different rectification responsibility still resolves correctly without M3.4 code changes.

If the final recipient set is empty, the command must fail before Activity/Notification persistence.

## Manual ActionItem recipient resolution

For one target ActionItem, each active candidate user must be evaluated for:

```text
update_assigned_action
```

Acceptance must prove:

- Process Review v1 primary/collaborator behavior works only through Scenario authorization;
- unrelated same-Finding or same-Case grants cannot authorize sibling Action recipients;
- inactive users are excluded;
- cross-Organization users are excluded;
- the sender is excluded from self-delivery; and
- a custom Scenario can change valid Action responsibility without requiring hard-coded role updates in M3.4.

## Recipient snapshot semantics

For both manual and automatic paths, recipients are concrete active Users resolved at T0.

Acceptance must prove that later changes to:

- Case membership;
- Finding participants;
- Action assignees;
- department membership; or
- Scenario-derived authority

do not rewrite historical Notification recipients already persisted.

Notification delivery history remains historical evidence only and grants no live subject access.

## Manual nudge Activity provenance

Each successful manual nudge must create exactly one Activity with:

- exact typed Finding or ActionItem subject;
- authenticated sender as `actor_id`;
- a dedicated nudge event type; and
- timezone-aware occurrence time.

All Notifications emitted by that nudge must reference that exact Activity identity.

The required chain is:

```text
manual nudge
  -> exact Activity N
  -> recipient resolution/delivery
  -> Notification.origin_activity_id = N
```

Hard Gate failures include:

- latest-Activity lookup;
- subject + event_type lookup after append;
- timestamp matching;
- Activity-history scanning;
- probabilistic provenance recovery; or
- creating a separate Activity per Notification recipient for one manual nudge occurrence.

PostgreSQL concurrency/provenance tests must be capable of creating same-subject, same-event-type, near-concurrent nudges and prove each Notification set stays bound to its own exact Activity.

## Manual transaction atomicity

A manual nudge Activity and all required in-app Notifications commit atomically.

Acceptance must prove both directions:

1. successful nudge commits exactly one Activity plus all deduplicated recipient Notifications; and
2. forced Notification persistence failure rolls back the manual nudge Activity.

The transaction must not modify ReviewCase/Finding/ActionItem lifecycle, responsibility relationships, Submission rows, Workbench truth, or management progress facts.

## Manual Notification dedupe

Within one manual nudge Activity, one concrete recipient receives at most one Notification for the same kind even if candidate resolution reaches that user by multiple legal paths.

The stable logical uniqueness remains equivalent to:

```text
organization
+ recipient
+ exact nudge Activity
+ notification kind
```

Acceptance must prove:

- duplicate recipient discovery creates one row;
- concurrent insertion for the same logical delivery creates one row;
- different recipients may each receive one row from the same Activity; and
- two deliberately separate manual nudges may legitimately create two different Activities and two later Notifications.

Title/body matching and `SELECT before INSERT` are forbidden dedupe strategies.

## Automatic reminder semantic scope

The later automatic path may evaluate only deadlines already present as Review Core facts:

```text
ReviewCase.planned_end_at
ActionItem.due_at
```

The factual overdue predicates must remain identical to M3.3:

```text
ReviewCase overdue
= planned_end_at < as_of
  AND lifecycle in {scheduled, in_progress}

ActionItem overdue
= due_at < as_of
  AND lifecycle in {todo, in_progress}
```

Terminal states and null deadlines are excluded.

No `Finding.due_at` or heuristic Finding deadline may be introduced.

The seven-day M3.3 due-soon window is not automatically a delivery rule. Exact due-soon/overdue cadence remains outside this first Gate.

## Automatic recipient resolution

### ReviewCase

Current active candidates must be evaluated with exact historical Scenario authorization for:

```text
transition_case
```

### ActionItem

Current active candidates must be evaluated for:

```text
update_assigned_action
```

Acceptance for the later implementation must prove:

- exact historical ScenarioVersion is used, not latest version/key-only lookup;
- custom Scenario behavior can differ from Process Review v1;
- no hard-coded `lead`, `primary`, or `collaborator` recipient shortcut exists;
- target-specific authorization prevents sibling grant leakage;
- inactive users are excluded;
- `system_admin` is not an implicit recipient; and
- cross-Organization recipients are impossible.

## Automatic reminder Activity boundary

Automatic reminder execution must append **no Review Activity merely because a timer condition was true**.

Acceptance must explicitly compare Activity count before and after an automatic reminder evaluation and prove it is unchanged.

A future implementation is allowed to persist collaboration-owned idempotency/provenance facts if required by the approved schema, but it may not fabricate:

```text
review_case.reminder_timer_fired
finding.reminder_timer_fired
action_item.reminder_timer_fired
```

or equivalent Review Activity solely to satisfy Notification `origin_activity_id`.

This is a hard boundary between human nudge audit history and timer-driven delivery history.

## Notification provenance evolution

M3.2 event-backed Notifications remain Activity-backed and unchanged in meaning.

The later M3.4 implementation must support an automatic reminder provenance identity that is not a fake Activity.

The persistence design must enforce an exactly-one logical origin equivalent to:

```text
Activity-backed origin
OR
Automatic-reminder stable origin
```

The exact physical columns/types are an Implementation Gate decision, but Acceptance must reject any design where:

- existing M3.2 Notifications lose their exact Activity identity;
- automatic reminders use an unrelated/guessed Activity;
- automatic reminder dedupe depends on title/body; or
- one schema field ambiguously means both Activity ID and arbitrary reminder token.

## Automatic reminder idempotency

Repeated evaluation of one logical automatic reminder occurrence must create at most one Notification per recipient.

The database-enforced logical uniqueness must be equivalent to:

```text
organization
+ recipient
+ notification kind
+ typed subject
+ stable reminder occurrence key
```

The occurrence key must survive:

- repeated scans;
- process restart;
- concurrent executors;
- transaction retry; and
- duplicate candidate discovery.

Deadline identity must participate in the logical occurrence semantics so that changing a Case `planned_end_at` or Action `due_at` does not allow an old occurrence key to suppress a legitimate reminder for the changed deadline.

Acceptance must prove:

- same logical occurrence, same recipient -> one Notification under concurrency;
- same logical occurrence, different recipients -> one each;
- changed persisted deadline can produce a new logical occurrence when policy says it should;
- terminalizing the target before persistence prevents stale delivery; and
- `SELECT before INSERT` is not the concurrency-control mechanism.

Exact cadence/occurrence-bucket construction remains deferred until cadence is reviewed.

## Manual vs automatic kind separation

The eventual Notification catalog must distinguish at least these semantic categories:

```text
manual_finding_nudge
manual_action_nudge
automatic_case_reminder
automatic_action_reminder
```

Manual and automatic deliveries must not share one kind whose meaning is inferred from nullable fields.

Existing M3.2 Notification kinds remain unchanged.

## Read-side and lifecycle regression gate

M3.4 implementation Acceptance must prove:

- Workbench membership/responsibility/deadline results remain current-state projections;
- Management progress/deadline results remain unchanged in semantics;
- Notification inbox still lists historical user deliveries only;
- mark-read still changes only `read_at` and appends no Activity;
- manual nudge does not change Case/Finding/Action lifecycle;
- automatic reminder does not change Case/Finding/Action lifecycle;
- reminder Notifications do not grant subject access; and
- existing M2 concurrency invariants remain green.

## Query/scaling boundary

Recipient resolution may bulk-read candidate relationship facts, but SQL must be category-bounded rather than one repository chain per candidate.

Acceptance should compare small and large candidate sets and prove there is no obvious N+1 growth.

Bulk reads never permit one combined same-Case grant bag to authorize sibling targets.

No speculative Review Core indexes may be added without PostgreSQL query evidence.

## Privacy/error boundary

The later manual nudge API must use existing BusinessIdentity authentication and established non-disclosing resource semantics.

Acceptance must prove:

- unauthenticated access follows existing auth failure behavior;
- known foreign/unauthorized target UUIDs do not reveal existence;
- zero-recipient business validation does not leak hidden candidate details;
- another user's Notification remains inaccessible; and
- a nudge Notification ID never becomes a capability token for live subject access.

## Scheduler/cadence exclusion gate

Before this first design PR can be accepted, diff review must prove there is no implementation of:

```text
scheduler
cron
background scan
polling loop
periodic task
reminder cadence
escalation
snooze
quiet hours
preferences
email/webhook/IM/push
```

The first Gate deliberately defines semantics without choosing execution infrastructure.

## Regression baseline

At implementation time, the full merged M3.3 baseline must remain green before counting M3.4 additions.

Current merged M3.3 evidence is:

```text
pytest: 224 passed / 1 existing warning
Alembic: 0001 -> 0010
Ruff: pass
mypy: pass
architecture check: pass
OpenAPI check: pass
```

The implementation PR must add PostgreSQL tests for M3.4-specific concurrency, exact provenance, dedupe, recipient isolation, and no-lifecycle-side-effect guarantees.

## Gate exit decision

This first Architecture & Acceptance Gate is releasable for implementation only when review agrees that:

1. **manual nudge** is an explicit, Activity-backed human collaboration action;
2. **automatic reminder** is a timer/policy delivery and does not fabricate Review Activity;
3. manual sender authority comes from existing exact Scenario management semantics, not role names/platform role;
4. recipient resolution uses exact historical Scenario authorization and target-specific contexts;
5. manual Finding recipients are current `submit_rectification`-authorized users;
6. manual/automatic Action recipients are current `update_assigned_action`-authorized users;
7. automatic Case recipients are current `transition_case`-authorized users;
8. Notification dedupe has separate stable logical origins for Activity-backed and automatic reminder deliveries;
9. no generic Finding deadline, reminder workflow entity, scheduler, or cadence is introduced in this Gate; and
10. M2/M3.1/M3.2/M3.3 semantics remain stable.

Until that review occurs, the PR remains Draft and M3.4 implementation must not begin.
