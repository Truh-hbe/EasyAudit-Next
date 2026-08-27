# M3.2 Acceptance Gate

M3.2 is ready for Implementation Gate only when the architecture review accepts this document. It is ready for Final Architecture Review only when CI proves all implementation requirements below.

## Architecture boundary

- Notification is a dedicated Collaboration & Management entity, not a Review Core entity and not a WorkItem/TodoTask replacement.
- ReviewCase/Finding/ActionItem lifecycle values, Scenario workflow semantics, concurrency guards, lock order, Submission rules, and M3.1 Workbench semantics remain unchanged.
- Review Core domain and Scenario implementations do not import the notifications module.
- Notification creation does not become a new authorization source or business-state predicate.
- `ReviewCoreRepository` is not expanded with Notification-inbox or recipient-query methods.
- No email/webhook/IM/push transport, Scheduler, reminder cadence, escalation, management dashboard, or frontend UI is added.
- `system_admin` receives no implicit access to another user's business notifications.

## Persistence contract

PostgreSQL must persist one user-specific Notification with at least:

```text
id
organization_id
recipient_user_id
kind
origin_activity_id
typed ReviewCase/Finding/ActionItem subject
title
body
created_at
read_at nullable
```

CI must prove:

- recipient, origin Activity, and subject are organization-safe;
- a Notification cannot target another Organization's User or subject;
- the subject is typed and exactly one supported target is present;
- delivery facts cannot be mutated by ordinary application paths after insert;
- delete is not exposed as an ordinary API operation; and
- only `read_at` has the narrow mutable semantics required by M3.2.

## Event/Notification transaction atomicity

For every M3.2 trigger integrated into an existing request path, the business mutation, its append-only Activity, and required in-app Notification inserts use the same request transaction.

PostgreSQL integration tests must prove both directions:

1. successful business mutation commits its Activity and all required Notification rows together; and
2. forced Notification persistence failure rolls back the business mutation and Activity rather than leaving a committed event without its required M3.2 notification.

M3.2 must not move external delivery into this transaction because external delivery is outside scope.

## Trigger catalog

The first implementation must cover at least these business occurrences:

- Case membership added;
- Finding participant added;
- Action assignee added; and
- Finding submitted for verification.

Each occurrence must use the existing Activity produced by the M2 write path as the durable event/idempotency origin rather than inventing a competing lifecycle event log.

Approval/rejection informational notifications, Case completion notifications, comments/mentions, deadline reminders, repeated overdue reminders, escalation, and user preferences remain outside the required Gate unless separately added to scope before implementation.

## Direct recipient semantics

CI must prove:

- a newly added CaseMember User receives one Notification;
- a direct FindingParticipant User receives one Notification;
- a direct ActionAssignee User receives one Notification;
- unrelated same-organization users do not receive those Notifications; and
- users in another Organization never receive them.

Platform role alone must not produce a recipient.

## Department recipient snapshot

Where the exact Scenario role legally supports a Department relationship, CI must prove:

```text
Department relationship at T0
        ↓
active users whose primary_department_id == Department at T0
        ↓
concrete user Notification rows
```

Required assertions:

- active matching Department users receive the Notification;
- inactive users do not;
- users in another Department do not;
- users in another Organization do not;
- the Notification stores concrete recipients, not a Department recipient row;
- direct-vs-department business relationship semantics remain unchanged; and
- later Department membership changes do not retroactively rewrite the historical Notification recipients.

## Verification notification authorization

`Finding submitted for verification` is a hard Scenario gate.

For each candidate recipient the implementation must resolve the parent Case's exact persisted ScenarioVersion and evaluate:

```text
ScenarioPolicy.authorization.allows(
    "verify_finding",
    target_specific_context,
)
```

CI must prove:

- Process Review v1 currently notifies its legitimate verifier(s) without Workbench/Notification code comparing `role_key == reviewer`;
- a same-organization user not allowed to `verify_finding` receives no verification Notification;
- `system_admin` without the Scenario business authority receives no verification Notification;
- authorization facts from sibling Findings/Actions cannot leak into the target Finding context; and
- a test Scenario with verification authority different from Process Review v1 still produces the correct recipient set without modifying notification code.

The test Scenario must be capable of exposing a hard-coded reviewer or Case-wide grant-bag implementation.

## Candidate discovery and scaling

The Gate does not require verification-recipient computation to be independent of organization user count.

It does require:

- database reads to be bulk/category-oriented rather than one query per candidate/resource relationship;
- target-specific authorization contexts after bulk reads;
- no per-user chain of repository calls that causes obvious N+1 growth; and
- no Process Review-specific candidate shortcut introduced solely to narrow SQL.

If the exact Scenario contract legally permits `is_active_organization_user` to influence verification authority, candidate discovery must remain semantically complete even if this means evaluating a broader active-user set.

## Idempotency / deduplication

CI must prove one logical Notification per:

```text
organization
recipient
origin Activity
notification kind
```

At minimum:

- retrying/reprocessing the same Activity does not create a duplicate row;
- the same recipient reached through multiple valid relationship paths receives one row for the same event/kind; and
- different recipients may each receive one row from the same Activity.

The database must enforce the deduplication key or an equivalent stable uniqueness invariant. String matching on title/body is not acceptable.

## Inbox API

`GET /api/v1/me/notifications` must:

- use the existing BusinessIdentity dependency;
- filter by authenticated `organization_id + recipient_user_id` before materialization;
- return only the caller's rows;
- support bounded pagination/limit rather than an unbounded history load;
- order newest first by a deterministic `(created_at, id)` key;
- expose read/unread state; and
- document the response in OpenAPI.

CI must prove that another same-organization user's Notification and another Organization's Notification are absent even when their UUIDs are known.

If the response includes `unread_count`, it must count only the authenticated recipient's rows in the same Organization.

## Mark-read API

`POST /api/v1/me/notifications/{notification_id}/read` must:

- use the existing BusinessIdentity dependency;
- update only a row owned by the authenticated recipient and Organization;
- set `read_at` with a timezone-aware server timestamp;
- be idempotent when called repeatedly;
- never clear `read_at` in the first M3.2 contract;
- not mutate the referenced ReviewCase/Finding/Action; and
- not append Review Activity.

Cross-user/cross-organization Notification IDs must not disclose the row's existence through a special authorization response.

## Historical delivery vs live authorization

CI must preserve the distinction:

```text
Notification = message delivered historically
Subject access = current Scenario authorization
```

Possessing a Notification or subject UUID must never bypass the existing Review API authorization.

The Notification module must not add a `notification_recipient` grant to `AuthorizationContext` or otherwise turn delivery history into business authority.

## Index / query foundation

Notification-specific schema may add only indexes/constraints justified by:

- recipient inbox ordering/pagination;
- unread filtering/counting; and
- idempotency uniqueness.

Existing Review Core tables must not receive speculative Notification indexes unless PostgreSQL query evidence shows they are required by the implemented recipient-resolution path.

## OpenAPI and error contract

OpenAPI must include the list and mark-read endpoints and all Notification DTOs.

The API must preserve established privacy semantics:

- unauthenticated: existing authentication failure behavior;
- cross-organization or other-recipient Notification lookup: non-disclosing not-found behavior;
- malformed request/pagination values: request validation failure;
- persistence uniqueness races: handled without duplicate Notification delivery.

## Regression gate

- The full 195-test M3.1 baseline remains green before counting M3.2 additions.
- Existing Process Review end-to-end behavior remains unchanged in meaning.
- Existing PostgreSQL concurrency tests remain green.
- Existing Workbench same-Case isolation, verification authorization, system_admin boundary, deadline projection, and query-scaling tests remain green.
- Ruff, mypy, architecture checks, OpenAPI checks, and Alembic `0001 -> new head` migration checks remain green.

## M3.2 end-to-end proof

A PostgreSQL integration/API test must exercise at least this shape across two Organizations:

```text
Org A
├── User A: direct Case member
├── User B: direct Finding participant
├── Department D
│   ├── User C: active primary member
│   └── User D: inactive primary member
├── Action assigned to Department D (where test Scenario allows it)
├── Finding V: submitted for verification
│   ├── User E: exact Scenario-authorized verifier
│   └── User F: same-org but unauthorized
└── User G: system_admin with no business authority

Org B
└── User H
```

The proof must show:

- direct relationship events create the correct user-specific Notifications;
- Department fan-out includes C and excludes D/F/H as appropriate;
- verification submission notifies E and excludes F/G/H;
- one Activity cannot duplicate the same recipient/kind Notification;
- each user lists only their own inbox;
- mark-read affects only the caller's Notification; and
- forcing Notification persistence failure rolls back the associated business write + Activity.

The PR remains Draft and unmerged after implementation. M3.2 Final Architecture Review begins only after implementation and CI satisfy this document.