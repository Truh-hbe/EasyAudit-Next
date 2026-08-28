# M3.5.4 — Notification, Management & Reminder Product Surface Gate

Baseline:

```text
main@141b8ff38432584fce7a6fce916610a540ef4ef4
```

M3.5.4 starts only after M3.5.3 is merged and frozen. This Gate is **documentation-only**. No executable React/backend implementation is unlocked until the Architecture + Acceptance review passes.

M3.5.4 consumes the already-merged M3.2 Notification, M3.3 Management and M3.4 Reminder/Nudge capabilities. It does not redesign them for frontend convenience.

## Goal

Complete the first operational management/collaboration loop of the M3.5 Product Surface:

```text
persistent Notification inbox
        +
management progress / deadline view
        +
manual Finding / Action nudge affordance
        ↓
coherent React Product Surface
```

while preserving one hard invariant:

> **React may present and invoke M3.2/M3.3/M3.4 facts, but it must never become the canonical source of Notification delivery, management scope, deadline truth, reminder recipient selection, reminder provenance, or business authorization.**

The existing backend remains authoritative:

```text
M2 Review Core / exact Scenario Policy
        │
        ├── M3.2 Notification delivery history
        ├── M3.3 Management read projection
        └── M3.4 Scenario-owned nudge recipient resolution
                    ↓
              M3.5.4 Product Surface
```

The dependency arrow never reverses.

## Frozen upstream contracts

M3.5.4 begins from already-merged APIs and semantics.

### Notification

```http
GET  /api/v1/me/notifications?limit=&offset=
POST /api/v1/me/notifications/{notification_id}/read
```

The inbox wire exposes:

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

There is no M3.5.4 requirement for:

```text
mark unread
delete
archive
snooze
notification preference
recipient reassignment
server-side unread-only pagination
```

### Management

```http
GET /api/v1/management/review-cases
GET /api/v1/management/review-cases/{case_id}/progress
```

The collection accepts only the existing filters:

```text
review_plan_id
lifecycle
deadline_status = all | due_soon | overdue
limit
offset
```

The wire owns:

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

The progress detail additionally owns authorized Finding rows and deterministic overdue/due-soon Action deadline items.

### Manual nudge

```http
POST /api/v1/findings/{finding_id}/nudge
POST /api/v1/action-items/{action_item_id}/nudge
```

Both requests have **no recipient request body**.

The response is only:

```text
activity_id
recipient_count
```

Recipient identities remain server-resolved Scenario truth.

## Hard truth boundary

M3.5.4 must not independently answer any of these questions:

```text
Does this Notification still grant access to its subject?
Does this Notification mean the user still owns work?
Is this ReviewCase overdue?
Is this Action due soon?
Which hidden Finding contributed to a management total?
May this user manage this ReviewCase?
May this user send a nudge?
Who should receive this nudge?
Did a nudge create N Notifications?
Which historical Activity caused an event Notification?
Should an automatic reminder run now?
```

Those answers belong to the backend contracts already merged.

## Product information architecture

M3.5.4 replaces the existing M3.5.1 placeholders for:

```text
/me/notifications
/management
```

and may add:

```text
/management/review-cases
```

or use `/management` directly as the managed ReviewCase collection, provided the route hierarchy stays coherent with the frozen M3.5 architecture.

The existing original-resource routes remain canonical:

```text
/review-cases/:caseId
/findings/:findingId
/action-items/:actionItemId
```

Notification and Management do not gain independent copies of business detail pages.

## Notification Center semantics

The Notification Center answers:

> **What persisted messages were delivered to me?**

It does not answer:

> **What work currently belongs to me?**

That second question remains the M3.1 Workbench.

### Inbox row

A row may render only direct Notification wire facts and presentation derived from those facts:

```text
title
body
kind
created_at
read/unread presentation
subject kind
subject navigation hint
```

`origin_kind`, `origin_activity_id`, and `automatic_origin_key` may be retained in the wire DTO and may support narrow explanatory presentation, but the frontend must not reconstruct business provenance from Activity history or infer a current responsibility from origin metadata.

### Historical delivery is not capability

A Notification may remain visible after the recipient loses current access to the original ReviewCase/Finding/ActionItem.

Correct navigation behavior is:

```text
historical Notification row
        ↓ click
navigate to original typed subject route
        ↓
current subject API performs current authorization
        ↓
authorized → current resource renders
unauthorized/missing → existing safe unavailable state
```

Forbidden behavior:

```text
Notification exists
→ therefore target detail may be rendered from Notification/cache
```

Notification is never a capability token.

### Read state

`read_at` is recipient-local consumption state only.

Marking a Notification read must not alter:

```text
Activity
ReviewCase/Finding/Action lifecycle
responsibility relationships
Workbench membership
Management aggregates
deadline status
Reminder occurrence/provenance
```

The Product Surface sends only the existing mark-read command and treats its server response/refetch as truth.

### Unread and All tabs

The frozen M3.5 product architecture permits a first center with:

```text
未读
全部
```

However, the existing M3.2 list endpoint does **not** provide a server-side unread-only collection filter.

Therefore M3.5.4 must not falsely define client filtering of one paginated page as a complete unread collection.

The first implementation may use one of these safe presentations without changing backend semantics:

1. **All** is the paginated server inbox, with unread rows visually distinguished and `unread_count` shown as the global server-owned count; and **Unread** is explicitly a filter over the currently loaded page; or
2. keep one paginated inbox and expose an unread-count affordance rather than pretending to offer complete unread-only pagination.

A true paginated unread-only inbox requires a separately reviewed backend query extension. M3.5.4 must not silently invent it in React.

## Notification pagination

The Product Surface consumes the exact server `limit` / `offset` values and the returned ordered `items`.

It must not:

```text
query another user's inbox
merge Workbench items into Notification rows
reorder rows by guessed business urgency as if server order changed
construct a fake total from unread_count
```

`unread_count` is not the total Notification count.

If the UI needs “has next page”, it may determine that only from safe pagination information already present, for example `items.length == limit` meaning another page is possible, not guaranteed. It must not manufacture an authoritative total that the backend does not return.

## Notification subject navigation

The subject kind is already typed by M3.2. Route mapping may therefore be a closed presentation mapping:

```text
review_case → /review-cases/:id
finding     → /findings/:id
action_item → /action-items/:id
```

This mapping does not perform authorization and does not infer subject type from UUID shape, Notification kind, title/body text, Activity event type, or latest Activity.

Unknown future subject kinds must fail closed rather than route to an unrelated object.

## Management surface semantics

The Management surface answers:

> **For ReviewCases the backend currently authorizes me to manage, what progress and deadline facts does M3.3 project?**

It remains a read side.

M3.5.4 does not introduce:

```text
ManagementIssue
SupervisionTask
ManagementStatus
EscalationTicket
ManagementWorkflow
management-owned Finding/Action copies
```

### Collection

The collection renders server-owned `ManagementCaseSummary` facts.

Useful presentation may include:

```text
Case title
lifecycle
Scenario key/version
planned end
deadline bucket
Finding lifecycle counts
Action lifecycle counts / overdue / due soon
```

Filtering controls may map only to the existing backend filters.

React must not fetch raw Case/Finding/Action candidate sets and then reproduce M3.3 authorization/filter/pagination locally.

The correct flow remains:

```text
GET /management/review-cases
        ↓
already-authorized server collection
        ↓
React presentation
```

### Authorization-safe pagination remains server-owned

M3.3 defines external pagination over the final authorized management set.

M3.5.4 must preserve this by consuming the returned `items`, `total`, `limit`, and `offset` exactly.

Forbidden frontend behavior includes:

```text
request broad candidate page
→ filter unauthorized rows in React
→ recompute total
```

or combining Case collection pages in a way that changes observable server pagination semantics.

### `as_of` is one captured projection instant

Every M3.3 collection/progress response contains `as_of`.

The Product Surface must treat all deadline buckets and counts in that response as facts computed at that captured instant.

It must not run a client timer and mutate a server-projected Case/Action from `due_soon` to `overdue` locally when the wall clock crosses a deadline.

Freshness is obtained by refetching the backend projection.

### No percentage or competing KPI

M3.5.4 may visually summarize existing counts, but must not invent a cross-Scenario formula such as:

```text
overall progress = 73%
risk score = 82
management health = red/yellow/green
```

unless such a metric is already a server wire fact. It currently is not.

### Management progress detail

A managed ReviewCase may open the existing M3.3 progress response.

The view may render:

```text
case summary
visible Finding rows
per-Finding Action counts
overdue Action items
due-soon Action items
```

Each Finding/Action link navigates to the original resource route, which rechecks current target authorization.

Management visibility does not authorize the original resource UI by itself.

## Manual nudge Product Surface

The first nudge affordance remains deliberately small:

```text
催一下
```

It is not a new workflow.

M3.5.4 may expose it on:

```text
Finding detail
ActionItem detail
management progress rows as a shortcut
```

provided every button invokes the existing command against the **original Finding or ActionItem ID**.

A management row does not become the mutation owner.

### No recipient picker

The frontend sends no recipient ID, department ID, role key, permission key or recipient policy input.

Forbidden request state includes:

```text
selectedRecipients
recipientUserIds
recipientDepartmentIds
nudgeRole
recipientPermission
```

Recipient resolution remains:

```text
current target facts
+ exact persisted ScenarioVersion
+ Scenario collaboration recipient intent
+ active same-organization relationships
→ concrete recipients
```

on the backend.

The response `recipient_count` may be displayed as the server-confirmed fan-out count. It does not authorize the frontend to reconstruct recipient identities.

### Nudge sender authorization

A visible nudge button is never an authorization grant.

M3.4 requires the backend sender to satisfy current management and target-specific Scenario authorization. The Product Surface may hide a button when the current resource state makes a nudge obviously irrelevant, but it must always treat the command result as authoritative.

No frontend condition such as:

```ts
role === "lead"
platform_role === "system_admin"
```

may prove nudge authority.

### Nudge result and refresh

On success:

```text
POST nudge
→ server returns activity_id + recipient_count
→ Product Surface shows confirmation
→ affected historical views may be refetched when useful
```

The frontend must not append a locally fabricated `Notification` or `Activity` row.

A sender usually does not receive their own manual nudge because M3.4 excludes the sender from recipient resolution; therefore the sender's personal Notification inbox is not a reliable proof that the nudge happened.

`activity_id` is the server's audit/provenance result. The UI may present success using it indirectly, but must not search Activity history to “find the matching nudge” or infer Notification IDs from it.

### Nudge failure

Existing API semantics are authoritative:

```text
404 → target/current sender scope not disclosed or target unavailable
422 → visible/authorized request has no eligible recipients or another frozen validation failure
```

Any future 409/other state conflict introduced by a separately reviewed backend contract must also remain authoritative.

On failure M3.5.4 creates no local recipient, Activity, Notification, escalation or “pending nudge” truth.

## Automatic reminder boundary

M3.4 contains automatic reminder backend semantics and delivery history, but M3.5.4 does not introduce scheduler administration.

The Product Surface may display automatic reminder Notifications already present in the user's inbox because they are ordinary persisted Notification delivery records with typed automatic origins.

It must not expose controls for:

```text
run reminder sweep
next reminder time
cadence
repeat interval
snooze
quiet hours
escalation threshold
recipient override
deduplication key
automatic origin key authoring
```

Automatic origin keys are backend provenance/deduplication facts, not user-editable configuration.

## Scenario boundary

Notification and Management presentation are generic backend wire concerns and do not require generic pages to branch on Scenario identity.

Manual nudge recipients are already Scenario-owned on the backend. React does not need a Scenario adapter to choose recipients.

If a future Scenario needs different explanatory copy, it may use the existing centralized exact Scenario UI registry only for presentation. It must not move recipient resolution, deadline truth or nudge authorization into the adapter.

## Shared API boundary

All new Product calls must use the existing shared frontend API transport.

Feature components must not scatter raw `fetch()` calls or create parallel DTO/business models.

Expected bounded feature ownership is conceptually:

```text
web/src/features/notifications/
web/src/features/management/
web/src/features/reminders/   (or collaboration/)
```

Exact file names are an implementation choice.

`ProductShell.tsx` remains routing/navigation composition, not the workflow implementation.

## Cache, session and route isolation

The M3.5.1–3 protected-state rules continue to apply:

- logout/session identity changes clear protected Product state;
- route changes do not reuse command messages or drafts from another business target;
- a stale Notification/Management row never bypasses current target authorization;
- old asynchronous responses from a prior route/filter/page must not overwrite the current view;
- a mark-read or nudge response from a stale identity/route must not mutate the new identity's visible state.

## Backend prerequisite policy

M3.5.4 should be frontend-dominant because M3.2/M3.3/M3.4 already expose executable APIs.

Any proposed backend change must stop implementation and be evaluated as a narrow prerequisite if it is required to preserve an already-frozen invariant.

The following are **not** acceptable “UI prerequisites” inside this slice:

```text
new Notification business lifecycle
new management permission
new manager role
new reminder recipient contract
new scheduler/cadence
new Finding deadline
new management aggregate persistence
new arbitrary recipient API
new Notification total/unread query semantics merely for prettier tabs
```

## M3.5.4 explicit non-goals

This slice does not add:

```text
new Review Core lifecycle or permission
Notification delete/archive/mark-unread
user Notification preferences
push/email/webhook delivery
complex charts/dashboard builder
custom KPI formulas
management workflow/tasks
Finding deadline
recipient picker
ReviewCase manual nudge
scheduler controls
reminder cadence policy
snooze/escalation/quiet hours
manual automatic-reminder trigger
WebSocket/live updates
AI summaries
M3.5.5 visual polish program
```

## Gate discipline

Before approval, the branch must remain exactly docs-only:

```text
docs/architecture/m3-5-4-notification-management-reminder-surface.md
docs/architecture/m3-5-4-acceptance.md
```

No `web/**`, executable backend source, migration, package/lockfile, CI/workflow or generated contract changes are allowed before the Gate passes.

After approval:

```text
Gate PASS
→ executable implementation
→ focused frontend/backend prerequisite tests if approved
→ exact-head normal CI
→ Final Architecture / Implementation Review
→ expected-head protected merge
```

## Final architecture test

M3.5.4 succeeds only if a reviewer can delete the React implementation and still point to exactly one backend owner for every relevant business question:

```text
Notification delivery/read truth      → M3.2
management scope/progress/deadline    → M3.3
nudge sender/recipient/provenance      → M3.4
business lifecycle/authorization      → M2 exact Scenario + Review Core
```

If React becomes necessary to answer any of those questions canonically, the Gate has failed.