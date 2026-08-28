# M3.5.4 — Notification, Management & Reminder Product Surface Gate

Baseline:

```text
main@141b8ff38432584fce7a6fce916610a540ef4ef4
```

M3.5.4 starts only after M3.5.3 is merged and frozen. This Gate is **documentation-only**. No executable React/backend implementation is unlocked until Architecture + Acceptance review passes.

M3.5.4 consumes merged M3.2 Notification, M3.3 Management and M3.4 Reminder/Nudge capabilities. It may add one narrowly reviewed Notification query prerequisite required by the already-frozen parent M3.5 `未读 / 全部` product contract; it does not redesign Notification semantics.

## Goal

Complete the first operational management/collaboration loop:

```text
persistent Notification inbox
        +
management progress / deadline view
        +
manual Finding / Action nudge
        ↓
coherent React Product Surface
```

while preserving:

> **React may present and invoke M3.2/M3.3/M3.4 facts, but it must never become canonical Notification delivery, management scope, deadline, reminder-recipient, provenance, lifecycle, or authorization truth.**

Dependency direction remains:

```text
M2 Review Core / exact Scenario Policy
        │
        ├── M3.2 Notification
        ├── M3.3 Management read side
        └── M3.4 Scenario-owned nudge recipients
                    ↓
              M3.5.4 Product Surface
```

The arrow never reverses.

## Frozen upstream contracts

### Notification — existing

```http
GET  /api/v1/me/notifications?limit=&offset=
POST /api/v1/me/notifications/{notification_id}/read
```

Existing inbox wire:

```text
items[]
  id
  kind
  origin_kind
  origin_activity_id | null
  automatic_origin_key | null
  subject
    kind = review_case | finding | action_item
    id
  title
  body
  created_at
  read_at | null

unread_count
limit
offset
```

Notification is historical recipient-local delivery. `read_at` is consumption state only.

### Notification — approved narrow M3.5.4 query prerequisite

The parent M3.5 Product Surface already freezes a Notification Center with:

```text
未读
全部
```

The current M3.2 endpoint has no server-side unread-only collection filter. Filtering a single paginated page in React cannot represent a complete unread view.

M3.5.4 therefore explicitly approves one additive query prerequisite:

```http
GET /api/v1/me/notifications?unread_only=true|false&limit=&offset=
```

with these semantics:

```text
recipient-local organization scope
        ↓
if unread_only=true: read_at IS NULL
        ↓
deterministic inbox ordering
        ↓
limit / offset
```

The filter MUST occur **before pagination**.

Default:

```text
unread_only = false
```

preserves the existing M3.2 API behavior.

This prerequisite must not change:

```text
Notification schema
recipient ownership
read_at semantics
origin/provenance semantics
ordering semantics
mark-read semantics
Notification kinds
```

and requires no migration.

`unread_count` remains the global unread count for the current recipient, including when `unread_only=true`.

The query does not add an inbox total. It is not a new Notification lifecycle or Workbench projection.

No other Notification backend affordance is approved in this Gate.

### Management — existing

```http
GET /api/v1/management/review-cases
GET /api/v1/management/review-cases/{case_id}/progress
```

Collection filters remain exactly:

```text
review_plan_id
lifecycle
deadline_status = all | due_soon | overdue
limit
offset
```

Server wire owns:

```text
as_of
total
limit
offset
ReviewCase deadline_bucket
Finding lifecycle counts
Action lifecycle counts
Action overdue / due_soon counts
```

Progress detail owns authorized Finding rows and overdue/due-soon Action deadline items.

### Manual nudge — existing

```http
POST /api/v1/findings/{finding_id}/nudge
POST /api/v1/action-items/{action_item_id}/nudge
```

Both requests have no recipient body.

Response:

```text
activity_id
recipient_count
```

Recipient identities stay Scenario-owned backend truth.

## Hard truth boundary

M3.5.4 must not independently decide:

```text
whether Notification receipt grants current subject access
whether Notification means current work ownership
whether a Case/Action is overdue or due soon
which hidden children contributed to a management aggregate
whether the user may manage a Case
whether the user may nudge a target
who receives a nudge
which Activity caused a Notification
whether an automatic reminder should run now
```

## Product routes

M3.5.4 replaces placeholders for:

```text
/me/notifications
/management
```

It may add `/management/review-cases` if useful, but original resources remain canonical:

```text
/review-cases/:caseId
/findings/:findingId
/action-items/:actionItemId
```

Notification and Management do not acquire duplicate detail domains.

## Notification Center

The center answers:

> **What persisted messages were delivered to me?**

It does not answer:

> **What work currently belongs to me?**

That remains M3.1 Workbench truth.

### All / Unread views

The first Product Surface implements two real server-backed views:

```text
全部 → unread_only=false
未读 → unread_only=true
```

Both views use the same recipient-local Notification model, ordering and offset/limit pagination.

React must not:

- fetch All and locally pretend a page filter is the complete Unread collection;
- merge Workbench items into the inbox;
- use `unread_count` as total inbox size;
- query another recipient by ID.

`unread_count` is a global server-owned unread badge/count, not pagination total.

### Inbox row

A row may render direct wire facts:

```text
title
body
kind
created_at
read/unread state
subject kind/navigation hint
```

`origin_kind`, `origin_activity_id`, and `automatic_origin_key` are historical provenance metadata only. React must not reconstruct provenance by scanning Activity history or matching timestamps/event types.

### Notification is not capability

Historical receipt remains visible even after current target access is revoked.

Navigation:

```text
Notification typed subject
        ↓
original resource route
        ↓
current target GET
        ↓
authorized → render current resource
refused/missing → existing safe unavailable state
```

Notification payload/cache never substitutes for current target authorization.

### Typed subject routing

Closed mapping:

```text
review_case → /review-cases/:id
finding     → /findings/:id
action_item → /action-items/:id
```

Subject type must not be guessed from Notification kind, title/body, UUID, Activity type or origin.

### Read state

Mark read calls only the existing endpoint and treats server response/refetch as truth.

Reading must not alter:

```text
Activity
Review Core lifecycle
responsibility relationships
Workbench membership
Management aggregates/deadlines
Reminder occurrence/provenance
```

No mark-unread/delete/archive/snooze exists in M3.5.4.

## Management surface

M3.3 remains a read side.

No:

```text
ManagementIssue
SupervisionTask
ManagementStatus
EscalationTicket
ManagementWorkflow
```

### Collection

React consumes the already-authorized M3.3 envelope directly.

It may present:

```text
Case title/lifecycle
Scenario key/version
planned timing
deadline bucket
Finding lifecycle counts
Action lifecycle / overdue / due-soon counts
```

Filters map only to existing backend query parameters.

React must not load broad Case/Finding/Action candidates and reproduce management authorization or pagination locally.

### Authorization-safe pagination

M3.3 external pagination is already defined over the final authorized management set.

M3.5.4 consumes returned:

```text
items
total
limit
offset
```

without filtering hidden candidates in React or recomputing `total`.

### `as_of` boundary

All deadline facts in one response are valid at the captured server `as_of`.

React must not run a wall-clock timer that mutates a server `due_soon` bucket into `overdue`. Freshness comes from refetching M3.3.

### No invented KPI

No frontend canonical:

```text
overallProgress
risk score
health score
weighted completion
Finding overdue
```

unless future backend contracts add those facts.

### Progress drill-down

The management progress surface may render:

```text
case summary
visible Finding rows
per-Finding Action counts
overdue Action items
due-soon Action items
```

Finding/Action links navigate to original resources and re-run current target authorization.

Management visibility is not a capability token.

## Manual nudge Product Surface

The first affordance stays small:

```text
催一下
```

It may appear on:

```text
Finding detail
ActionItem detail
management progress Finding/Action rows as shortcuts
```

Every shortcut invokes the existing command on the original Finding/Action ID.

ReviewCase manual nudge remains out of scope.

### Recipient truth

Frontend request state must not contain:

```text
recipientUserIds
recipientDepartmentIds
selectedRecipients
nudgeRole
recipientPermission
recipientIntent
```

Recipient resolution remains:

```text
current target facts
+ exact persisted ScenarioVersion
+ Scenario collaboration recipient semantics
→ concrete active same-organization recipients
```

The response `recipient_count` may be displayed. It does not disclose or authorize recipient identities.

### Sender authorization

Button visibility is presentation only.

No React rule such as:

```ts
role === "lead"
platform_role === "system_admin"
```

may prove nudge authority.

The backend M3.4 sender authorization and target-specific checks remain final.

### Success / failure

Success:

```text
POST nudge
→ activity_id + recipient_count
→ server-confirmed success presentation
→ optional refetch
```

React must not append fake Activity or Notification rows. The sender's own inbox is not success proof because the sender is excluded from their own manual nudge recipient set.

Failures remain authoritative:

```text
404 → unavailable/non-disclosing sender/target scope
422 → visible/authorized request has no eligible recipient or frozen validation failure
```

No local pending-reminder/nudge lifecycle is created.

## Automatic reminder boundary

Automatic reminder Notifications already persisted by M3.4 may render in the inbox.

Historical automatic Notification existence does not prove current overdue/accountability or a future next run.

No controls for:

```text
run sweep
scheduler
cadence
repeat interval
next reminder
snooze
quiet hours
escalation
recipient override
dedup/origin-key authoring
```

## Shared frontend API boundary

All calls use the existing shared frontend API transport.

Expected bounded ownership:

```text
web/src/features/notifications/
web/src/features/management/
web/src/features/reminders/  or collaboration/
```

`ProductShell.tsx` stays routing/navigation composition.

No raw feature-local fetch clients or second business DTO models.

## Protected-state and async isolation

M3.5.1–3 rules continue:

- logout/login clears protected Notification/Management state;
- old page/filter/route responses cannot overwrite current state;
- stale Notification/Management rows never bypass target authorization;
- a nudge result from Finding A cannot become Finding B's command result;
- a mark-read result from user/session A cannot mutate user/session B's inbox.

## Approved backend change boundary

M3.5.4 is frontend-dominant, with **one explicitly approved backend prerequisite only**:

```text
GET /me/notifications
+ optional unread_only query
+ filter before pagination
```

Allowed implementation touch points are limited to the Notification query path and focused tests, for example:

```text
notifications/api.py
notifications/service.py
notifications/persistence.py
Notification query tests
```

only as required to implement that filter.

No migration/schema change is expected.

Any other backend need stops implementation for architecture review.

Forbidden “UI prerequisites” include:

```text
new Notification lifecycle
inbox total merely for cosmetics
new management permission/manager role
new reminder recipient contract
new arbitrary-recipient API
new scheduler/cadence
new Finding deadline
new management aggregate persistence
```

## Explicit non-goals

M3.5.4 does not add:

```text
Review Core lifecycle/permission changes
Notification mark-unread/delete/archive
Notification preferences
push/email/webhook delivery
complex chart/dashboard platform
custom KPI formulas
management workflow/tasks
Finding deadline
recipient picker
ReviewCase manual nudge
scheduler controls
cadence/snooze/escalation/quiet hours
manual automatic-reminder trigger
WebSocket/live updates
AI summaries
M3.5.5 broad visual-polish program
```

## Gate discipline

Before approval the diff remains exactly:

```text
docs/architecture/m3-5-4-notification-management-reminder-surface.md
docs/architecture/m3-5-4-acceptance.md
```

No executable source, `web/**`, migration, package/lockfile, workflow/CI or generated contract changes before Gate PASS.

After approval:

```text
Gate PASS
→ narrow unread query prerequisite + Product implementation
→ focused tests
→ exact-head normal CI
→ Final Architecture / Implementation Review
→ expected-head protected merge
```

## Final architecture test

M3.5.4 succeeds only if every canonical question still has one backend owner:

```text
Notification delivery/read/unread query → M3.2 + narrow recipient-local query extension
management scope/progress/deadline      → M3.3
nudge sender/recipient/provenance        → M3.4
business lifecycle/authorization        → M2 exact Scenario + Review Core
```

If React becomes necessary to answer those questions canonically, the Gate has failed.