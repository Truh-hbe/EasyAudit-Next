# M3.5.4 — Notification, Management & Reminder Product Surface Acceptance Gate

Baseline:

```text
main@141b8ff38432584fce7a6fce916610a540ef4ef4
```

This Acceptance belongs to `m3-5-4-notification-management-reminder-surface.md` and is frozen before executable implementation begins.

M3.5.4 is accepted only if the Product Surface consumes M3.2 Notification, M3.3 Management and M3.4 Reminder/Nudge without creating competing frontend business truth.

## A. Gate diff acceptance

Before executable implementation is unlocked:

```text
changed files == 2
```

and the exact paths are:

```text
docs/architecture/m3-5-4-notification-management-reminder-surface.md
docs/architecture/m3-5-4-acceptance.md
```

Forbidden before Gate approval:

```text
web/**
src/easyaudit_next/**
alembic/**
package / lockfile
GitHub Actions / CI
OpenAPI generated artifacts
```

## B. Upstream contract acceptance

The implementation must consume exactly the existing first-slice APIs unless a separately reviewed prerequisite is approved.

Notification:

```http
GET  /api/v1/me/notifications?limit=&offset=
POST /api/v1/me/notifications/{notification_id}/read
```

Management:

```http
GET /api/v1/management/review-cases
GET /api/v1/management/review-cases/{case_id}/progress
```

Manual nudge:

```http
POST /api/v1/findings/{finding_id}/nudge
POST /api/v1/action-items/{action_item_id}/nudge
```

Acceptance fails if frontend implementation requires an unreviewed endpoint for:

```text
arbitrary recipient selection
mark unread / archive / delete
Notification capability checks
client-generated reminder provenance
management task mutation
scheduler/cadence administration
Finding deadline
```

## C. Notification inbox ownership acceptance

`GET /me/notifications` is recipient-local historical delivery truth.

Tests must prove:

1. Product Surface calls only the current-user inbox endpoint; no recipient/user ID is supplied by React.
2. Rows come from the server `items` in their returned order.
3. The UI renders `title`, `body`, `kind`, `created_at`, `read_at` and typed subject without turning Notification into a Todo/WorkItem.
4. `unread_count` is rendered only as server-owned global unread count.
5. `unread_count` is never treated as total inbox size.
6. another user's Notification ID cannot be used to update local inbox truth when the server returns 404.
7. logout/login identity change clears protected Notification rows from the prior user.

No test may seed “authorization” by placing a Notification in local React state.

## D. Notification pagination acceptance

The existing inbox exposes `limit` and `offset`, but no total count.

Tests must show:

```text
page 0 response
→ UI renders exactly server page 0

next offset request
→ UI renders/appends according to the chosen presentation strategy
→ no fabricated total
```

If pages are accumulated for infinite-scroll style presentation, acceptance requires:

- deterministic server order remains intact;
- duplicate page responses do not create duplicate Notification rows;
- changing identity/resetting the inbox discards accumulated pages;
- a late response from an old offset/session cannot overwrite the current inbox.

The UI may say “more may be available” based on a full page. It must not assert an authoritative next page solely from `items.length == limit`.

## E. Unread presentation acceptance

The current server API has no unread-only pagination filter.

Therefore acceptance fails if Product copy or state claims that filtering the current loaded page is the complete unread inbox.

If the Product exposes an **未读** control, tests must prove either:

```text
explicit wording/state = current loaded page filter
```

or another equally clear non-authoritative presentation.

The global unread badge/count must continue to come from server `unread_count`.

Counterexample:

```text
server page contains 0 unread rows
server unread_count = 7
```

The UI must not conclude “没有未读通知” globally from the page contents.

## F. Mark-read acceptance

Mark read is the only Notification mutation in M3.5.4.

Tests must prove:

- unread Notification → POST exact Notification ID → server response/refetch owns `read_at`;
- already-read Notification → idempotent server response remains safe;
- server 404 leaves no fabricated `read_at` success;
- a failed mark-read does not decrement `unread_count` optimistically as durable truth;
- a successful mark-read updates/refetches inbox state coherently using server facts;
- mark-read creates no Activity, Workbench item, management fact or lifecycle transition in React.

If optimistic visual feedback is used, it must be rollback-safe and never become the only persisted truth. A simple server-confirmed update is preferred for this slice.

## G. Notification typed-subject navigation acceptance

The Product maps only the closed subject wire kind:

```text
review_case → /review-cases/:id
finding     → /findings/:id
action_item → /action-items/:id
```

Tests must prove:

1. subject route is derived from `subject.kind + subject.id`, not title/body text;
2. Notification `kind` is not used to guess resource type;
3. `origin_activity_id` is not used to guess resource type;
4. unknown future subject kind fails closed;
5. clicking does not render resource content from the Notification payload itself.

## H. Notification is not capability acceptance

Mandatory current-authorization counterexample:

```text
T0 user legitimately receives Notification for Finding F
T1 business relationship is revoked
T2 Notification remains in inbox
T3 user clicks Notification
```

Required result:

```text
Notification row remains historical delivery fact
→ route attempts current Finding GET
→ current backend refusal/missing state wins
→ safe unavailable page
→ no protected stale Finding content
```

Equivalent behavior must hold for ReviewCase and ActionItem target types through the existing resource route guards.

## I. Notification provenance acceptance

The inbox may carry:

```text
origin_kind
origin_activity_id
automatic_origin_key
```

Tests/static review must prove React does not:

```text
fetch latest Activity to explain Notification
scan Activity history for matching event_type
match timestamps
reconstruct Notification origin
invent automatic origin keys
```

For Activity-backed Notifications, the exact `origin_activity_id` is display/audit metadata only.

For automatic reminders, `automatic_origin_key` is opaque backend provenance/deduplication metadata, not user-editable state.

## J. Automatic reminder Notification acceptance

An automatic reminder Notification may appear like any persisted inbox item.

The Product may distinguish it using server `kind` / `origin_kind` presentation.

It must not infer:

```text
target is still overdue
recipient is still accountable
next reminder will occur
scheduler is active
```

from historical Notification existence.

A user must navigate/refetch current business/management truth for current state.

## K. Management collection acceptance

`GET /management/review-cases` remains the only collection truth.

Tests must prove React sends only supported filters:

```text
review_plan_id
lifecycle
deadline_status
limit
offset
```

and renders the server envelope:

```text
as_of
items
total
limit
offset
```

Acceptance fails if the Product fetches broad ReviewCases from another endpoint and rebuilds management scope in TypeScript.

## L. Authorization-safe management pagination acceptance

The frontend must preserve M3.3 authorize-before-pagination behavior.

Mandatory browser/API counterexample should retain the established pattern:

```text
visible A
hidden H1
visible B
hidden H2
visible C
limit = 2
```

Expected observable server-backed pages remain:

```text
page 1 = A, B
page 2 = C
```

Adding/removing hidden candidates must not alter visible page membership or authorized `total`.

The Product must consume those server pages without another client authorization filter that changes pagination semantics.

## M. Management filter acceptance

For each supported filter:

```text
review_plan_id
lifecycle
deadline_status = all | due_soon | overdue
```

browser tests must prove the filter causes a new backend management query and displays exactly returned results.

React must not implement a competing overdue predicate over Case dates for the authoritative collection.

Local text search/sort, if later introduced purely as presentation over the current loaded page, must be clearly non-authoritative and is not required by M3.5.4.

## N. Management `as_of` acceptance

Mandatory test:

```text
server response as_of = T0
Case C deadline_bucket = due_soon
wall clock moves past Case deadline without refetch
```

Required behavior:

```text
UI continues to display server projection from T0
```

until a fresh management request returns a new `as_of` / bucket.

React must not run a timer that promotes `due_soon → overdue` as authoritative business state.

## O. Management deadline/count fidelity

The Product renders exact server facts only:

ReviewCase:

```text
lifecycle
planned_start_at
planned_end_at
deadline_bucket
```

Finding counts:

```text
total
open
rectifying
verifying
closed
voided
```

Action counts:

```text
total
todo
in_progress
done
cancelled
overdue
due_soon
```

Tests/static review must prove no new frontend formula for:

```text
Finding overdue
Case percent complete
risk score
management health score
weighted progress
```

## P. Hidden-child aggregate privacy acceptance

M3.3 already excludes unauthorized Findings and their Actions from management aggregates.

Frontend acceptance must preserve this by consuming counts literally.

It must not supplement the management response with raw child collections in order to “complete” counts.

Counterexample:

```text
server management summary says findings.total = 2
raw Case happens to contain hidden sibling Finding H
```

The UI must show `2`, not query/derive `3`.

## Q. Management progress detail acceptance

The progress page uses:

```http
GET /api/v1/management/review-cases/{case_id}/progress
```

It may render:

```text
case
findings
overdue_actions
due_soon_actions
```

Tests must prove:

- 404 → safe unavailable management progress state;
- Finding rows link to `/findings/:id`;
- Action deadline rows link to `/action-items/:id`;
- current resource route GET remains the authorization gate after drill-through;
- progress response never becomes a cached replacement for the original Finding/Action page.

## R. Manual nudge placement acceptance

M3.5.4 may expose `催一下` on:

```text
Finding detail
ActionItem detail
management progress Finding/Action rows
```

Every affordance must call one of exactly:

```http
POST /findings/{finding_id}/nudge
POST /action-items/{action_item_id}/nudge
```

A management shortcut must send the original Finding/Action ID. No management-specific nudge aggregate/endpoint may be invented.

ReviewCase-level manual nudge is out of scope.

## S. No recipient picker acceptance

Static/browser tests must prove no M3.5.4 UI or request body contains arbitrary recipient selection.

Forbidden concepts include:

```text
recipient_user_ids
recipient_department_ids
selectedRecipients
role_key for nudge
permission for nudge
recipient intent selector
```

The network request body for both nudge endpoints must be empty apart from normal transport metadata.

## T. Nudge sender authorization acceptance

Button visibility is not authority.

Mandatory counterexamples:

```text
button rendered from stale UI
→ sender relationship revoked before click
→ backend 404
→ UI shows authoritative failure/refetch
→ no local nudge fact
```

and:

```text
system_admin without Scenario business scope
→ cannot gain nudge success from platform role
```

The frontend must contain no role/platform-role rule that proves nudge permission.

## U. Nudge recipient resolution acceptance

The Product never receives or reconstructs recipient identities from existing first-slice nudge APIs.

Success response:

```text
activity_id
recipient_count
```

Tests must prove:

- `recipient_count` may be displayed as server-confirmed delivery fan-out count;
- sender's own inbox is not treated as success proof;
- React does not map current Finding owner/Action assignee lists into recipients and compare against `recipient_count` as authority;
- no recipient list is cached as future nudge authority.

## V. Nudge success acceptance

Given a server success:

```text
POST /nudge
→ 200 response activity_id + recipient_count
```

Product behavior must be:

```text
show server-confirmed success
optionally refetch affected historical/resource views
```

It must **not**:

```text
append fake Notification row
append fake Activity row
create pending Reminder state
change target lifecycle
change target responsibility
```

Backend integration tests from M3.4 remain the proof that actual Activity + Notification facts persist atomically.

## W. Nudge failure acceptance

At minimum tests must cover:

```text
404 target/sender-scope refusal
422 no eligible recipients
```

Required result:

- no success banner;
- no fake `recipient_count`;
- no locally fabricated Activity/Notification;
- current target/management projection may be refetched where appropriate;
- no blind semantic retry.

If a stale server fact causes future 409 semantics, it must be treated equivalently as authoritative conflict.

## X. Automatic reminder controls forbidden acceptance

Static structure tests must prove M3.5.4 exposes no controls or API calls for:

```text
scheduler
sweep
cadence
repeat interval
next reminder
snooze
quiet hours
escalation
automatic origin key editing
manual automatic reminder trigger
```

Automatic reminders are visible only through existing persisted Notification facts and server management deadline facts.

## Y. Protected-state / route isolation acceptance

M3.5.1–3 state-isolation rules remain mandatory.

Tests must cover:

1. Notification page A request is slow; logout/login user B occurs; A's response cannot populate B's inbox.
2. Management filter/page request T0 is slow; filter/page changes to T1; T0 response cannot overwrite T1.
3. Nudge on Finding A is slow; route switches to Finding B; A's late success/failure must not display as B's command result.
4. mark-read on Notification A is slow; session identity changes; A's result cannot mutate the next user's inbox state.

Request cancellation or request-identity epochs are implementation choices; observable isolation is mandatory.

## Z. Shared API boundary acceptance

All M3.5.4 network calls must flow through the existing shared frontend API boundary.

Acceptance fails if feature components:

```text
call raw fetch independently
redeclare inconsistent wire DTOs
create client-side business entities for Notification/Management/Reminder
```

Direct wire DTO typing is allowed; TypeScript types are not authorization/deadline/recipient truth.

## AA. Frontend ownership acceptance

Expected bounded modules should look conceptually like:

```text
features/notifications
features/management
features/reminders | collaboration
```

Acceptance fails if:

- `ProductShell.tsx` becomes Notification/Management/Nudge business logic;
- generic components branch on `process_review` to decide recipients or management authority;
- M3.5.4 adds a second management workflow store;
- Notification becomes a local Todo state machine.

## AB. No M3.5.5 leakage acceptance

M3.5.4 should remain focused on functional Product Surface.

It may make the minimum layout changes required to render the new pages, but must not expand into a broad final-polish program such as:

```text
theme engine
major visual redesign
animation system
charting platform
full mobile navigation redesign
internationalization framework
```

Those belong to M3.5.5/future work unless strictly required for functional accessibility.

## AC. Accessibility baseline

Functional controls added in this slice must remain:

- keyboard reachable;
- semantically labeled;
- non-color-only for read/deadline/status meaning;
- accompanied by readable loading/error/empty states;
- usable at the already-supported narrow browser width for essential actions.

M3.5.5 will perform broader responsive/final polish; M3.5.4 must not regress the established baseline.

## AD. Backend prerequisite acceptance

Default expectation:

```text
M3.5.4 backend executable changes == 0
```

If implementation discovers a genuine prerequisite, work stops and the prerequisite must be architecture-reviewed separately or explicitly added to this Gate before executable change.

A backend change is not justified merely because a richer UI would prefer:

```text
inbox total
server unread filter
recipient preview
manager role
new KPI
new scheduler controls
```

## AE. Required regression / CI evidence

Final executable head must pass the repository normal exact-head CI, including at minimum:

```text
Ruff
mypy
architecture checks
OpenAPI checks
Alembic migration path
PostgreSQL pytest regression
frontend typecheck
frontend lint
frontend unit/component tests
frontend production build
mocked browser Product acceptance
real PostgreSQL + FastAPI browser acceptance
```

Focused M3.5.4 frontend tests must cover Notification, Management and nudge success/refusal/stale-state behavior.

Existing M3.2/M3.3/M3.4 PostgreSQL tests remain authoritative backend regression evidence unless a separately approved backend prerequisite is introduced.

## AF. Final fixed-head review acceptance

Before merge:

1. PR remains open / Draft / unmerged until Final Review PASS.
2. base must still be the intended current `main` or the feature branch must explicitly absorb any intervening prerequisite through a reviewable merge.
3. exact candidate head is frozen.
4. normal CI on that exact head is `completed / success`.
5. compare against current main shows no unauthorized scope expansion.
6. Final Architecture / Implementation Review finds no P1/P2.
7. PR exits Draft only after those conditions are satisfied.
8. merge uses expected-head protection with the fixed candidate SHA.
9. merge commit parents/tree/new main are verified after merge.

## AG. Final acceptance statement

M3.5.4 is complete only when:

> an authenticated user can read and consume their persistent Notification history, inspect only the management progress the backend authorizes, navigate those projections back to original resources, and invoke existing Finding/Action manual nudges while Notification delivery/read state, management scope/deadlines, recipient resolution, provenance, lifecycle and authorization remain backend-owned.

If React becomes the canonical answer to “who should receive this reminder?”, “is this work overdue?”, “may this user manage/nudge it?”, or “what current work does this Notification represent?”, the Gate has failed.