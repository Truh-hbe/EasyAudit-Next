# M3.5.4 — Notification, Management & Reminder Product Surface Acceptance Gate

Baseline:

```text
main@141b8ff38432584fce7a6fce916610a540ef4ef4
```

This Acceptance belongs to `m3-5-4-notification-management-reminder-surface.md` and is frozen before executable implementation begins.

M3.5.4 is complete only if React consumes M3.2/M3.3/M3.4 truth without creating competing business state, while the already-frozen parent M3.5 `未读 / 全部` Notification Center is implemented with pagination-correct server semantics.

## A. Gate diff acceptance

Before implementation unlock:

```text
changed files == 2
```

and exactly:

```text
docs/architecture/m3-5-4-notification-management-reminder-surface.md
docs/architecture/m3-5-4-acceptance.md
```

Forbidden before Gate PASS:

```text
web/**
src/easyaudit_next/**
alembic/**
package / lockfile
workflow / CI
OpenAPI generated artifacts
```

## B. Frozen API surface

Existing Notification APIs:

```http
GET  /api/v1/me/notifications?limit=&offset=
POST /api/v1/me/notifications/{notification_id}/read
```

Approved additive query prerequisite:

```http
GET /api/v1/me/notifications?unread_only=true|false&limit=&offset=
```

Existing Management APIs:

```http
GET /api/v1/management/review-cases
GET /api/v1/management/review-cases/{case_id}/progress
```

Existing manual nudge APIs:

```http
POST /api/v1/findings/{finding_id}/nudge
POST /api/v1/action-items/{action_item_id}/nudge
```

No other Product API expansion is approved by this Gate.

## C. Unread query prerequisite acceptance

The narrow Notification extension must satisfy all of:

1. `unread_only` is optional and defaults to `false`.
2. `false` preserves current M3.2 inbox behavior and ordering.
3. `true` constrains the current recipient's organization-scoped inbox to `read_at IS NULL`.
4. unread filtering happens **before** `limit / offset`.
5. deterministic existing Notification ordering is preserved.
6. `unread_count` remains the current recipient's global unread count.
7. response schema is unchanged.
8. no Notification schema/migration is introduced.
9. no mark-unread/delete/archive semantics are introduced.
10. no recipient/user ID can be supplied by the client.

Mandatory PostgreSQL/query counterexample:

```text
ordered inbox:
U1, R1, U2, R2, U3

unread_only=true
limit=2 offset=0 → U1, U2
limit=2 offset=2 → U3
```

The implementation fails if it performs:

```text
limit/offset full inbox
→ filter unread afterwards
```

because that would make unread page membership depend on read rows.

## D. Notification Center All / Unread acceptance

The first Product Center exposes two real server-backed views:

```text
全部 → unread_only=false
未读 → unread_only=true
```

Browser tests must prove switching views issues the correct backend query and does not reuse page membership from the other view.

Counterexample:

```text
All page contains no unread rows at current offset
unread_count > 0
```

The UI must not claim globally “没有未读通知”; the Unread view must query `unread_only=true`.

`unread_count` is never treated as inbox total.

## E. Notification ownership acceptance

The Product calls only `/me/notifications`; React supplies no recipient ID.

Tests must prove:

- rows come only from server `items`;
- another user's Notification cannot be read/marked through local state;
- 404 on mark-read creates no local success;
- logout/login clears protected inbox state;
- a late response from user/session A cannot populate user/session B's inbox.

Notification remains delivery history, not Workbench/current ownership.

## F. Notification pagination acceptance

For each view, React consumes server `limit` and `offset` without inventing a total.

If pages are accumulated:

- order remains server order;
- duplicate page responses do not duplicate rows;
- changing All/Unread resets or correctly partitions pagination state;
- changing identity resets accumulated pages;
- an old offset/view response cannot overwrite the current view.

`items.length == limit` may mean another page is possible, not guaranteed.

## G. Mark-read acceptance

Mandatory behavior:

```text
unread row
→ POST exact notification_id/read
→ server response/refetch owns read_at
```

Tests cover:

- unread success;
- already-read idempotent success;
- 404 refusal;
- server-confirmed `unread_count` refresh/update;
- no Activity/lifecycle/Workbench/Management/Reminder mutation in React.

A successful mark-read in Unread view removes the item only according to server-confirmed state/query refresh, not because React independently changed durable truth.

## H. Typed subject navigation acceptance

Route mapping uses only:

```text
subject.kind + subject.id
```

Accepted mapping:

```text
review_case → /review-cases/:id
finding     → /findings/:id
action_item → /action-items/:id
```

Forbidden routing inference:

```text
Notification kind
title/body text
UUID shape
origin_activity_id
Activity event type
latest Activity
```

Unknown future subject kinds fail closed.

## I. Notification is not capability acceptance

Mandatory counterexample:

```text
T0 Notification for Finding F delivered legitimately
T1 user's current Finding visibility is revoked
T2 historical Notification remains
T3 user clicks row
```

Required result:

```text
navigate to /findings/F
→ current Finding GET is authorization gate
→ refusal/missing wins
→ safe unavailable page
→ no stale protected Finding content
```

Equivalent original-resource guard behavior applies to ReviewCase/ActionItem subjects.

## J. Notification provenance acceptance

React may render narrow historical origin presentation from wire facts, but static/browser review must prove it does not:

```text
lookup latest Activity
scan Activity history
match event_type/timestamp
reconstruct origin
invent automatic_origin_key
```

`origin_activity_id` and `automatic_origin_key` are opaque historical provenance/deduplication facts, not current responsibility or workflow truth.

Automatic reminder Notification existence must not be presented as proof the target is still overdue or that another reminder is scheduled.

## K. Management collection acceptance

React uses only:

```http
GET /api/v1/management/review-cases
```

with supported filters:

```text
review_plan_id
lifecycle
deadline_status = all | due_soon | overdue
limit
offset
```

It renders the returned:

```text
as_of
items
total
limit
offset
```

and server summary facts.

Acceptance fails if React loads broad ReviewCase/Finding/Action sets and rebuilds management scope locally.

## L. Authorization-safe management pagination acceptance

The established M3.3 semantics remain observable.

Mandatory counterexample:

```text
A, H1, B, H2, C
limit=2
```

where H1/H2 are hidden candidates.

Required authorized pages:

```text
page 1 = A, B
page 2 = C
```

Hidden candidate insertion/removal must not alter visible page membership or authorized `total`.

React must not add another client authorization filter that changes these server semantics.

## M. Management filter acceptance

Changing `review_plan_id`, `lifecycle`, or `deadline_status` must issue a new management query and render exactly returned results.

React must not implement an authoritative overdue filter over raw dates.

## N. Management `as_of` acceptance

Mandatory counterexample:

```text
server as_of=T0
Case C deadline_bucket=due_soon
browser wall clock later crosses deadline
```

Without refetch, UI remains the T0 server projection.

Freshness is obtained only by requesting a new M3.3 projection.

## O. Management count/deadline fidelity acceptance

Render only server-owned facts:

ReviewCase:

```text
lifecycle
planned_start_at
planned_end_at
deadline_bucket
```

Finding counts:

```text
total open rectifying verifying closed voided
```

Action counts:

```text
total todo in_progress done cancelled overdue due_soon
```

Forbidden frontend canonical metrics:

```text
Finding overdue
overall progress percentage
risk score
health score
weighted completion
```

## P. Hidden-child privacy acceptance

If management summary says `findings.total=2`, React displays `2` even if another raw endpoint could expose a broader Case collection to a different authorization context.

It must not supplement M3.3 counts by independently loading children to “complete” aggregates.

Hidden siblings must not leak through locally recomputed totals.

## Q. Management progress acceptance

Use only:

```http
GET /api/v1/management/review-cases/{case_id}/progress
```

The Product may render:

```text
case
findings
overdue_actions
due_soon_actions
```

Tests cover:

- 404 safe unavailable state;
- Finding links to original `/findings/:id`;
- Action links to original `/action-items/:id`;
- drill-through rechecks current original-resource authorization;
- progress DTO never replaces original business detail truth.

## R. Manual nudge placement acceptance

Allowed `催一下` surfaces:

```text
Finding detail
ActionItem detail
management progress Finding/Action shortcuts
```

Every affordance invokes only:

```http
POST /findings/{finding_id}/nudge
POST /action-items/{action_item_id}/nudge
```

using the original resource ID.

No ReviewCase manual nudge.

## S. No recipient picker acceptance

Static/browser network tests prove no request body or client state contains:

```text
recipient_user_ids
recipient_department_ids
selectedRecipients
role_key for recipient selection
permission for recipient selection
recipient-intent selector
```

Both nudge requests are bodyless business commands.

## T. Nudge sender authorization acceptance

Button presence is presentation only.

Mandatory stale counterexample:

```text
button rendered
→ sender business relationship revoked
→ click
→ backend 404
→ authoritative failure/refetch
→ no local nudge fact
```

`system_admin` without Scenario business scope gains no client bypass.

No React role/platform-role rule may prove nudge authority.

## U. Nudge recipient acceptance

On success, React receives only:

```text
activity_id
recipient_count
```

Tests prove:

- `recipient_count` may be displayed;
- recipient identities are neither inferred nor cached;
- Finding owner / Action assignee lists are not transformed into canonical nudge recipients;
- sender inbox is not used as proof of delivery.

## V. Nudge success/failure acceptance

Success:

```text
POST nudge
→ activity_id + recipient_count
→ server-confirmed success UI
→ optional authoritative refetch
```

React must not append fake Notification/Activity rows or create pending Reminder state.

Failure tests cover at minimum:

```text
404 target/sender-scope refusal
422 no eligible recipients
```

Required:

- no success banner/fake recipient count;
- no local Activity/Notification;
- no blind retry;
- optional target/management refetch where useful.

Future backend 409 conflict, if separately introduced, is likewise authoritative.

## W. Automatic reminder controls forbidden acceptance

Static structure tests prove no Product controls/API calls for:

```text
scheduler
sweep
cadence
repeat interval
next reminder
snooze
quiet hours
escalation
recipient override
automatic origin/dedup key editing
manual automatic-reminder trigger
```

Automatic reminders are visible only as persisted Notification history plus current server management facts.

## X. Async/route/session isolation acceptance

Mandatory browser races:

1. Notification request for user A is slow; login changes to B; A result cannot render in B inbox.
2. All-view request is slow; switch to Unread; All result cannot overwrite Unread state.
3. Management filter/page T0 is slow; query changes to T1; T0 cannot overwrite T1.
4. Finding A nudge is slow; route moves to Finding B; A result cannot become B command status.
5. mark-read for Notification A is slow; identity changes; old response cannot mutate next user's inbox.

Implementation may use AbortController, request sequence IDs, route epochs or equivalent; observable isolation is mandatory.

## Y. Shared API boundary acceptance

All calls use existing shared frontend API transport.

Acceptance fails if feature components:

```text
scatter raw fetch
redeclare divergent wire DTOs
create client business entities for Notification/Management/Reminder
```

TypeScript DTOs remain direct wire representation, not authority.

## Z. Frontend ownership acceptance

Bounded ownership should resemble:

```text
features/notifications
features/management
features/reminders | collaboration
```

`ProductShell.tsx` remains routing/navigation composition.

Generic pages must not branch on `process_review` to decide management scope, deadlines, recipient sets or nudge authority.

## AA. Accessibility / M3.5.5 boundary

New controls must retain existing baseline:

- semantic labels;
- keyboard reachability;
- non-color-only read/deadline/status meaning;
- loading/error/empty states;
- essential narrow-width usability.

M3.5.4 must not expand into M3.5.5's broad responsive/visual-polish program.

## AB. Backend executable boundary acceptance

Exactly one backend capability extension is pre-approved:

```text
/me/notifications optional unread_only query
```

Implementation may touch only the narrow Notification query path and focused tests as necessary.

Expected properties:

```text
no migration
no schema change
no Notification kind/origin change
no new lifecycle
no other endpoint
```

Any additional backend requirement stops implementation for architecture review.

Not approved merely for UI convenience:

```text
inbox total
mark unread/archive/delete
recipient preview/override
new manager role/permission
new KPI
new Finding deadline
new scheduler/cadence
```

## AC. Required backend tests for unread prerequisite

At minimum PostgreSQL/integration tests must prove:

- default query preserves current inbox;
- unread filter occurs before pagination;
- ordering deterministic;
- recipient/org isolation;
- `unread_count` remains global unread count;
- mark-read changes membership of later unread queries only through persisted `read_at`;
- invalid pagination still rejected by existing API bounds.

## AD. Required frontend Product tests

Focused unit/browser acceptance must cover:

```text
All / Unread server-backed pagination
mark-read success/refusal
historical Notification → currently unauthorized target
Notification async identity isolation
Management authoritative filters/pages/total/as_of
management hidden-child privacy
management drill-through
Finding/Action nudge success
nudge 404/422 refusal
no recipient body/picker
nudge route race
no scheduler controls
```

## AE. Normal exact-head CI acceptance

Final executable head must pass repository normal CI on that exact SHA:

```text
Ruff
mypy
architecture checks
OpenAPI checks
Alembic migration path
PostgreSQL pytest
frontend typecheck
frontend lint
frontend unit/component tests
frontend production build
mocked browser Product acceptance
real PostgreSQL + FastAPI browser acceptance
```

## AF. Final fixed-head review acceptance

Before merge:

1. PR remains Draft/open/unmerged until Final Review PASS.
2. base is current intended main, or any intervening prerequisite is explicitly absorbed through a reviewable merge.
3. candidate head is fixed.
4. exact-head normal CI is `completed / success`.
5. compare against current main shows only approved M3.5.4 scope.
6. Final Architecture / Implementation Review finds no P1/P2.
7. PR exits Draft only after PASS.
8. merge uses `expected_head_sha`.
9. merge parents/tree/new main are verified.

## AG. Final acceptance statement

M3.5.4 is complete only when:

> an authenticated user can browse complete server-backed All/Unread Notification views, mark their own delivery records read, inspect only management progress authorized by M3.3, drill back to original resources, and invoke existing Finding/Action nudges while Notification delivery/read state, management scope/deadlines, recipient resolution, provenance, lifecycle and authorization remain backend-owned.

If React becomes canonical for “which Notifications are unread?”, “who should receive this nudge?”, “is this work overdue?”, “may this user manage/nudge it?”, or “what current work does this historical Notification represent?”, the Gate has failed.