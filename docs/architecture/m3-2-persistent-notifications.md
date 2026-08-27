# M3.2 — Persistent Notifications

M3.2 is the second Collaboration & Management slice. It builds on the merged M3.1 Workbench and adds a durable in-app notification record without creating a second task truth, changing Review Core workflow semantics, or introducing reminder scheduling.

## Goal

Provide one authenticated, persistent notification inbox answering: **what business events were delivered to me?**

M3.2 introduces first-party in-app persistence only. Email, webhook/IM delivery, periodic deadline scanning, reminder cadence, escalation, and management dashboard behavior remain outside this slice.

The initial API surface is expected to include:

```http
GET  /api/v1/me/notifications
POST /api/v1/me/notifications/{notification_id}/read
```

The list API is bounded and deterministically ordered. It may expose an unread count and cursor/pagination metadata, but it must not become a second Workbench endpoint.

## Notification is a delivery record, not business truth

A persisted `Notification` means that a message was delivered to one concrete user at one point in time.

It must not mean:

- the recipient currently owns the Case/Finding/Action;
- the recipient currently has business authority over the subject;
- the subject is still open, overdue, or awaiting verification;
- the notification itself is a Todo/WorkItem that drives workflow; or
- reading the notification changes any Review Core lifecycle.

The authoritative business state remains:

```text
ReviewCase / CaseMember
Finding / FindingParticipant
ActionItem / ActionAssignee
Submission
Activity
ScenarioPolicy.authorization
```

M3.1 Workbench remains the current-state projection. M3.2 Notification is historical delivery state.

Therefore:

> **Notification may point at work, but Notification is never the work.**

## Persistence shape

M3.2 introduces a dedicated Notification model under a separate collaboration module, not under Review Core.

The exact SQL/ORM naming may vary after implementation review, but the persisted facts must represent at least:

```text
Notification

id
organization_id
recipient_user_id
kind
origin_activity_id

subject
  ReviewCase OR Finding OR ActionItem

title
body

created_at
read_at nullable
```

The subject must be typed. A generic UUID without a closed subject type is not acceptable. The implementation may use typed nullable FK columns such as `review_case_id`, `finding_id`, and `action_item_id` with an exactly-one-target invariant.

`recipient_user_id` is always a concrete User. Department relationships are resolved to concrete users when the Notification is created; a Department is never stored as an inbox recipient.

`origin_activity_id` identifies the durable M2 business event that caused an event-backed notification. M3.2 event notifications therefore have a stable idempotency anchor.

## Organization-safe persistence

Notification persistence must preserve the same cross-organization guarantees as M1/M2.

At minimum:

- recipient User and Notification belong to the same Organization;
- origin Activity and Notification belong to the same Organization;
- the typed subject and Notification belong to the same Organization; and
- repository/API lookups require `(organization_id, id)` rather than trusting UUID possession.

Strong composite foreign keys should be used where the current schema already exposes the required organization-safe key shape.

`system_admin` receives no implicit ability to read another user's business notifications.

## Structural immutability

Notification delivery facts are immutable after creation:

```text
recipient
kind
origin activity
subject
title/body
created_at
```

must not be rewritten by ordinary application paths.

Only recipient-local read state is mutable:

```text
read_at: NULL -> timestamp
```

The first M3.2 API does not require mark-unread or delete semantics. Mark-read is idempotent and must not rewrite Review Activity or business state.

If database enforcement is used, it should reject UPDATEs to delivery facts and DELETEs while permitting the narrow `read_at` transition.

## Event-backed creation and transaction boundary

For the first M3.2 slice, business-event notifications are materialized in the same request-scoped PostgreSQL transaction as the triggering business mutation and its append-only Activity.

The required cutover is:

```text
business authorization / Scenario validation
        ↓
Review Core mutation
        ↓
Activity append
        ↓
return exact mutation result + Activity identity
        ↓
resolve Notification recipients
        ↓
insert Notification rows
        ↓
request transaction commit
```

A committed event that is in the M3.2 trigger catalog must not silently lose its required in-app Notification rows.

Likewise, if Notification persistence fails before commit, the request transaction must roll back rather than committing a partial business mutation plus Activity without the required M3.2 delivery record.

This atomicity applies only to first-party in-app persistence. Future external delivery such as email/webhook must not be placed inside the Review Core transaction.

M3.2 must not implement this by database triggers that contain Scenario or recipient business logic.

## Exact origin Activity propagation

For every event-backed Notification, `origin_activity_id` must come from the exact `Activity` instance created by the triggering mutation in the current request transaction.

The collaboration orchestration layer must receive that identity synchronously from the Review Core application operation. It must not attempt to reconstruct provenance after the mutation has returned.

The required dependency shape is:

```text
Review Core mutation
        ↓
create exact Activity A
        ↓
Scenario-neutral mutation result
(entity/result + ActivityId(A))
        ↓
M3.2 collaboration orchestration
        ↓
recipient resolution
        ↓
Notification.origin_activity_id = ActivityId(A)
```

The exact implementation type may be operation-specific, for example:

```text
CaseMemberAddedResult
├── member
└── activity_id

FindingParticipantAddedResult
├── participant
└── activity_id

ActionAssigneeAddedResult
├── assignee
└── activity_id

RectificationSubmissionResult
├── submission
├── finding
└── activity_id
```

or an equivalently type-safe Scenario-neutral application result.

`ActivityId` is application-operation output. It must not be added as a new property of `CaseMember`, `FindingParticipant`, `ActionAssignee`, `Submission`, or other Review Core entities merely to support Notification.

The following provenance-recovery patterns are forbidden:

- selecting the latest Activity for a subject;
- querying Activity by `subject + event_type` after the mutation;
- timestamp matching;
- scanning Activity history and choosing a probable row; or
- any other post-mutation lookup that guesses which Activity belongs to the current operation.

This rule is required even when all writes share one transaction. Concurrent requests may create the same event type for the same subject, and timestamp/order-based recovery can bind a Notification to the wrong Activity. Because Activity identity participates in Notification idempotency and audit provenance, such a mismatch is a data-integrity failure.

Review Core may therefore expose Scenario-neutral mutation results containing the exact created Activity identity. This does not make Review Core depend on Notification. The dependency remains one-way: Review Core produces generic operation facts; M3.2 consumes them.

## Trigger catalog for the first slice

M3.2 is intentionally narrower than a complete notification-policy engine. The first implementation must cover the collaboration events that establish new work or new verification responsibility:

1. **Case membership added** — notify the newly added User.
2. **Finding participant added** — notify the direct User, or resolve a Department participant to eligible active users in that Department.
3. **Action assignee added** — notify the direct User, or resolve a Department assignee to eligible active users where that Scenario role legally supports department-derived participation.
4. **Finding submitted for verification** — notify every user for whom the exact historical Scenario Policy allows `verify_finding` on that target Finding.

The implementation must map these occurrences to the existing append-only Activity emitted by the M2 write path. It must not create a second lifecycle event vocabulary that competes with Activity.

Approval/rejection informational messages, Case completion messages, email delivery, mentions/comments, deadline reminders, repeated overdue reminders, escalation, and user notification preferences are deferred unless separately reviewed into scope.

## Recipient resolution

### Direct User relationships

A direct CaseMember, FindingParticipant, or ActionAssignee User relationship resolves to that exact active organization User.

No platform role is consulted as a substitute for the business relationship.

### Department relationships

When a valid Scenario relationship is stored against a Department, M3.2 resolves that Department to concrete active users using the platform's current department-membership model.

For the current platform model, that means active users whose `primary_department_id` is the target Department at notification-creation time.

Recipient resolution is a snapshot:

```text
relationship/event at T0
        ↓
resolve active department members at T0
        ↓
create user-specific Notification rows
```

Later department transfers do not rewrite historical Notification recipients.

The original relationship remains a Department fact; Notification fan-out must not rewrite or pretend that those users were direct `owner` / `primary` assignments.

### Verification recipient resolution

`finding.submitted_for_verification` is the hard Scenario boundary for M3.2.

The implementation must resolve the parent ReviewCase's persisted exact ScenarioVersion and ask:

```text
ScenarioPolicy.authorization.allows(
    "verify_finding",
    target_specific_authorization_context,
)
```

for candidate users.

It must not implement:

```text
role_key == reviewer
```

or any equivalent Process Review v1 shortcut.

The target-specific context rule established by M3.1 remains mandatory. Grants belonging to sibling Findings or sibling Actions must not authorize a user for this Finding's notification.

Because `AuthorizationContext` can legally express authority through different relationship combinations or `is_active_organization_user`, candidate discovery may be broader than Process Review v1's current reviewer set. M3.2 should prefer correct Scenario semantics over prematurely hard-coding a narrow candidate rule.

If later production scale proves candidate enumeration expensive, that becomes a separately reviewed Scenario-aware candidate-narrowing problem; it is not a reason to leak reviewer semantics into M3.2.

## Idempotency

One Activity may produce multiple recipient Notifications, but one recipient must not receive duplicate rows for the same logical notification when application code retries or recipient resolution reaches the same user through multiple paths.

The persistence layer must enforce a stable idempotency key equivalent to:

```text
organization_id
+ recipient_user_id
+ origin_activity_id
+ notification kind
```

A user who qualifies through both direct and department facts still receives one logical Notification for that Activity/kind.

Idempotency is not implemented by querying for a matching title/body string.

The exact Activity identity supplied by the triggering mutation is the provenance and idempotency origin. Notification code must not derive a replacement Activity identity from a later query.

## Notification does not grant live subject access

A Notification is historical delivery evidence. The recipient may keep seeing the message that was legitimately delivered to them, even if later business relationships change.

However, the Notification row itself must never authorize live subject access.

Opening or fetching the referenced ReviewCase/Finding/Action still goes through the current M2/M3 business authorization path and exact Scenario Policy. A Notification ID or subject UUID is never a capability token.

The persisted title/body should therefore be treated as message content already disclosed at delivery time, not as a substitute for the live business object representation.

## API boundary

`GET /api/v1/me/notifications`:

- uses the existing authenticated `BusinessIdentity`;
- scopes by `organization_id + recipient_user_id` before materialization;
- returns only that user's Notification rows;
- supports bounded pagination rather than returning an unbounded inbox;
- orders newest first by `(created_at, id)`; and
- may filter unread rows without changing persistence.

`POST /api/v1/me/notifications/{notification_id}/read`:

- can mutate only a Notification belonging to the authenticated recipient in the same Organization;
- sets `read_at` once using a timezone-aware server timestamp;
- is idempotent on repeated calls; and
- performs no Review Core mutation and appends no Review Activity.

Cross-user and cross-organization Notification IDs must not disclose whether a row exists.

## Query indexes

M3.2 may add Notification-specific indexes justified by the inbox query and unread count/filter, such as:

```text
notifications(organization_id, recipient_user_id, created_at DESC, id DESC)
notifications(organization_id, recipient_user_id, created_at DESC)
    WHERE read_at IS NULL
```

and the unique idempotency constraint/index described above.

Exact physical shapes remain query-plan driven. M3.2 must not add unrelated Review Core indexes merely because Notification references those resources.

## Module boundary

The intended dependency direction is:

```text
Review Core application operation
        ↓
Scenario-neutral mutation result + exact ActivityId
        ↓
application/composition collaboration orchestration
        ↓
notifications module
        ↓
Notification persistence / inbox API
```

Review Core domain models and Scenario implementations must not import the notifications module.

The notification module may consume Scenario-neutral persisted business facts and the exact Scenario Policy through the existing registry/composition wiring.

Do not add Notification-specific methods to the base `ReviewCoreRepository` merely for recipient resolution. Dedicated query/repository helpers are allowed inside the notifications slice.

Review Core application operations may expose Scenario-neutral mutation results containing the exact Activity identity they already create. They must not call `send_notifications()`, depend on `NotificationRepository`, render Notification templates, or otherwise import the notifications module.

The collaboration orchestration layer consumes the mutation result and creates Notification rows in the same request-scoped Session/transaction. It must never recover `origin_activity_id` by querying Activity after the mutation.

## Explicitly out of scope

M3.2 does not add:

- `WorkItem`, `TodoTask`, `InboxTask`, or a second responsibility table;
- Notification-driven Review lifecycle transitions;
- Scenario-specific notification templates inside Review Core;
- email, webhook, IM, SMS, or push transport;
- scheduler/cron/background deadline scanning;
- due-soon or overdue reminder generation;
- repeated reminder cadence, escalation, or snooze;
- management dashboard/query APIs;
- frontend notification center UI;
- user notification preferences; or
- a second Scenario.

M3.4 may later use the persistent Notification foundation to create reminder Notifications, but the seven-day M3.1 Workbench window does not automatically become a reminder policy here.

## End state

M3.2 is complete when PostgreSQL proves that selected existing business events atomically create deduplicated, organization-safe, user-specific Notification rows whose `origin_activity_id` is the exact Activity identity surfaced by the triggering mutation; department recipient fan-out preserves source semantics; verification-ready fan-out obeys exact Scenario authorization; users can list and mark only their own notifications as read; and M1/M2/M3.1 business semantics remain unchanged.