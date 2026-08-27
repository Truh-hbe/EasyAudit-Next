# M3.5 — Product Surface Architecture Gate

M3.5 is the final M3 Collaboration & Management slice. It begins only after M3.4 is merged and frozen.

Baseline:

```text
main@abf7801f336aa13634098d266defd2cd921dbdf5
```

This first M3.5 Gate is **design-only**. It freezes the product information architecture, frontend truth boundary, Scenario UI extension boundary, API-consumption rules, and acceptance shape before large-scale React implementation begins.

It must not change Review Core, Workbench, Notification, Management, or Reminder semantics.

## Goal

M3.1 through M3.4 established what EasyAudit-Next knows and can do. M3.5 makes those capabilities usable as one coherent long-lived Web product without creating a second frontend-owned business model.

The final M3.5 invariant is:

> **The Web product may compose and present existing backend capabilities, but it must not become an independent source of authorization, lifecycle, deadline, reminder-recipient, provenance, or task truth.**

Dependency direction remains:

```text
M2 Review Core
      │
      ├──────────────┐
      ▼              ▼
M3.1 Workbench    M3.2 Notification
      │              │
      ├──────┐       │
      ▼      ▼       ▼
M3.3 Management   M3.4 Reminder
      │              │
      └──────┬───────┘
             ▼
       M3.5 Product Surface
             │
          React UI
```

The arrow never reverses. Review Core and M3 backend modules do not import frontend/product-surface code.

## Hard boundary: frontend does not own business truth

The frontend must not independently decide or recompute:

```text
whether the current user is authorized
Finding overdue status
ActionItem overdue status
ReviewCase deadline risk
who should receive a reminder/nudge
whether a business transition is allowed
which historical Activity caused a Notification
whether a Notification changes current responsibility
```

Forbidden authorization truth includes logic equivalent to:

```ts
if (user.role === "reviewer" && finding.lifecycle === "verifying") {
  canApprove = true;
}
```

The UI may use server-returned state to decide presentation, visibility, wording, loading, and confirmation behavior. Every mutation remains server-authoritative and must still pass the exact backend Policy/Scenario/concurrency validation at request time.

If a future backend projection exposes typed `allowed_actions` / affordances, the Product Surface may consume it. M3.5 must not modify the M2 Scenario Contract merely to make React button logic convenient without a separate backend architecture review.

Until such a projection exists, the UI may use conservative/optimistic presentation plus authoritative mutation errors. A rendered button is never an authorization grant.

## Truth ownership matrix

| Concern | Authoritative owner | Product Surface responsibility |
|---|---|---|
| lifecycle | M2 Review Core / Scenario workflow | render returned lifecycle; submit commands |
| authorization | exact Scenario Policy + business relationships | render UX hints; handle authoritative refusal |
| Workbench membership | M3.1 Workbench read side | display and navigate |
| progress / overdue | M3.3 Management projections | display facts; never recompute competing rules |
| Notification history | M3.2 Notification | inbox/read UI and target navigation |
| reminder recipients | M3.4 Scenario-owned recipient policy | invoke nudge endpoint; never choose arbitrary users |
| reminder occurrence/provenance | M3.4 persisted delivery facts | display historical delivery facts if exposed |
| Scenario-specific fields | exact Scenario UI adapter + server Scenario data contract | render/edit supported scenario data only |

## Product information architecture

The first product shell has only these primary areas:

```text
我的工作
审查活动
通知
管理视图
管理设置
```

The default authenticated route is:

```text
/me/workbench
```

not a management dashboard.

The core product loop is:

```text
login
  ↓
What needs my attention?
  ↓
open ReviewCase / Finding / ActionItem
  ↓
perform an existing business action
  ↓
return to the Workbench
```

The shell must not force ordinary users through KPI dashboards before their actionable work.

## M3.5 route shape

Exact router spelling may evolve during implementation, but the conceptual route surface is frozen as:

```text
/me/workbench
/me/notifications

/review-cases
/review-cases/:caseId

/findings/:findingId
/action-items/:actionItemId

/management
/management/review-cases

/admin
```

A Workbench item, Notification, or Management row navigates to the original business object rather than creating a second detail domain.

## Workbench surface

M3.1 remains the sole source of the personal work projection. The frontend must not rebuild a second Workbench by separately querying Cases, Findings, and Actions and applying TypeScript rules.

The first surface may group existing M3.1 results into action-oriented sections such as:

```text
需要我处理
├── 待整改
├── 待协作
└── 待验证

时间风险
├── 即将到期
└── 已逾期

我参与的审查
├── 我牵头
└── 我参与
```

Grouping, sorting, labels, empty states, and visual priority are presentation decisions. Membership in those groups remains server-owned Workbench truth.

Workbench items are pointers to original ReviewCase/Finding/ActionItem resources. They have no independent lifecycle or detail page.

## ReviewCase surface

A ReviewCase page is the product's business-context container, not a CRUD form.

Recommended first structure:

```text
Case Header
├── title / identifier
├── lifecycle
├── Scenario
├── plan timing
└── key current facts

Tabs / sections
├── 概览
├── Findings
├── 成员
└── Activity
```

The overview consumes existing Case/Management facts such as:

```text
fieldwork state
Finding closure counts
Action completion counts
overdue counts
```

M3.5 must not invent an unapproved aggregate score such as `overallProgress = 67%`.

The Case page should answer:

- what stage is this review in now?
- what remains open?
- who participates?
- what has happened?

## Finding surface

Finding is the primary daily collaboration page.

Recommended first structure:

```text
Finding Header
├── title
├── lifecycle
├── severity
├── existing deadline/risk facts when available
└── responsibility

Main
├── problem description
├── Scenario-specific data
├── participants
├── Action Items
├── Submissions / Evidence
└── Activity Timeline
```

Business actions use existing backend commands such as issue, submit for verification, approve, reject, reopen, or void when the backend supports them.

The UI should not display every possible action simultaneously. It may conditionally present likely actions using server-returned facts, but backend authorization/workflow validation remains authoritative.

## ActionItem surface

ActionItem keeps the identity of a rectification action. It must not become a second Finding.

The page answers only:

```text
what must be done?
who is assigned?
when is it due?
is it complete?
what evidence exists?
```

M3.5 must not introduce Action-level `approved`, `rejected`, `pending_review`, or equivalent lifecycle truth merely to imitate a task-management product.

Formal verification approve/reject remains Finding verification unless Review Core is separately redesigned in a later architecture stage.

## Notification Center

M3.2 Notification remains a persistent business delivery object, not a toast archive.

The first center supports:

```text
通知
├── 未读
└── 全部
```

Each row should clearly communicate:

```text
what happened
which business object it concerns
when it happened
```

Clicking navigates to the original ReviewCase/Finding/ActionItem target when current authorization still permits access.

A Notification does not become a capability token. Historical receipt does not grant current subject access.

`read_at` is consumption state only. Reading a Notification must not alter Activity, lifecycle, responsibility, deadline, Workbench truth, or reminder occurrence truth.

A dedicated Notification detail domain is not required in the first product surface.

## Management surface

M3.3 remains a Read Side. The frontend must preserve that semantic boundary.

The first management view observes current facts such as:

```text
ReviewCase
├── plan / delay
├── fieldwork stage
└── closure stage

Finding
├── open
├── rectifying
├── verifying
├── overdue
└── closed

ActionItem
├── todo
├── in progress
├── overdue
└── done
```

Management rows drill into original business resources.

M3.5 must not introduce:

```text
ManagementIssue
SupervisionRecord
ExceptionTicket
ManagementTask
```

or any second management workflow.

A management page may expose an existing M3.4 nudge action as a shortcut. That button still invokes the M3.4 command against the original Finding/ActionItem and does not make the Management module a mutation owner.

## Manual nudge UI

The first manual reminder affordance is deliberately small:

```text
催一下
```

Only the existing M3.4 Finding and ActionItem nudge operations are represented.

The frontend must not submit arbitrary recipient IDs and must not introduce client-owned configuration for:

```text
reminder cadence
next reminder time
reminder lifecycle
snooze
escalation
quiet hours
```

If the backend later returns a recipient summary suitable for confirmation, the UI may display it. Recipient selection remains Scenario-owned backend truth.

## Scenario UI extension boundary

This is a hard M3.5 architecture requirement.

Scenario differences must not spread through generic React pages as checks equivalent to:

```tsx
if (scenarioKey === "process_review") {
  return <ProcessReviewFindingForm />;
}
```

A centralized Scenario UI extension point must exist before scenario-specific product behavior grows.

The conceptual boundary is:

```text
ScenarioUiRegistry

process_review@1
├── CaseScenarioSection
└── FindingScenarioSection
```

or an equivalent schema-driven renderer / typed adapter design.

The exact physical implementation is intentionally not frozen in this design PR. What is frozen:

1. generic Workbench/Case/Finding/Action/Notification/Management pages do not own Scenario identity branching;
2. Scenario-specific rendering is resolved through one centralized adapter/registry boundary;
3. exact Scenario version participates in adapter resolution when version changes can alter UI semantics;
4. adding a second Scenario should primarily add a new adapter, not edits to many generic pages; and
5. Scenario UI adapters render Scenario-specific data but do not redefine workflow authorization, lifecycle, deadline, recipient, or provenance truth.

M3.5 does **not** require a low-code form designer or universal schema engine. A small typed registry is sufficient for the first product.

## Scenario adapter responsibilities

A Scenario UI adapter may own presentation concerns such as:

```text
Scenario-specific field labels
field grouping
read-only display sections
editing widgets for server-defined scenario_data
Scenario-specific explanatory copy
```

It must not own:

```text
canApprove()
canReject()
isOverdue()
resolveReminderRecipients()
deriveLifecycle()
mapNotificationToHistoricalActivity()
```

Those remain backend truths.

## API consumption boundary

All Product Surface data and mutations flow through published backend HTTP APIs.

The frontend must have one shared API boundary responsible for:

```text
authenticated request transport
wire DTO typing
time parsing
standard error mapping
request cancellation/loading state
```

Feature pages should not scatter raw `fetch()` calls and hand-written inconsistent DTO copies.

OpenAPI remains the backend contract source. Generated TypeScript types/client code are preferred when practical; if implementation starts with a thin handwritten client, its DTOs must remain direct wire representations rather than a second business model.

Mirroring a backend enum for rendering is acceptable. TypeScript enum values do not become authority to invent transitions or authorization.

## Mutation consumption rules

The Product Surface must treat backend mutation responses/errors as authoritative.

At minimum the client must distinguish existing semantics for:

```text
401 / authentication failure
404 / non-disclosing unauthorized-or-missing resource behavior where established
409 / concurrency or state conflict
422 / request/business validation where established
```

The UI must not reinterpret a 409 stale-state failure as success because a locally cached lifecycle appeared valid.

After successful mutations, affected resource/query state is refreshed or invalidated through a defined data-fetching strategy. The frontend must not maintain a long-lived shadow lifecycle state that can diverge from the server.

The exact React data-fetching library is an implementation choice; introducing one does not alter domain semantics.

## Authentication surface

M3.5 consumes the existing server authentication/session contract. The frontend does not invent a parallel token or role cache as business authority.

Authentication state may be cached for UX, but server responses remain authoritative for active-session and resource access.

Logout/login/session-expiry behavior must return the user to a safe authentication route without exposing stale protected content.

## Presentation state is allowed

The frontend may own normal ephemeral UI state, including:

```text
selected tab
open modal/drawer
filter text
sort selection
pagination cursor/page presentation
expanded row
local unsaved form input
loading/error state
```

This Gate forbids second **business truth**, not ordinary client interaction state.

## Error and stale-data behavior

Business data can become stale between render and command.

The Product Surface must expect:

```text
render state T0
another actor mutates server truth
user submits at T1
backend rejects/returns new truth
```

The correct response is to surface the authoritative conflict, refresh the affected data, and let the user continue. The frontend must not bypass concurrency or retry a semantic mutation blindly.

## Accessibility and responsive boundary

M3.5 is a responsive Web product. It is not a mobile app or offline PWA.

The first version must remain usable on common desktop/laptop widths and narrow mobile browser widths for core viewing and essential collaboration actions.

Accessibility basics are part of product quality:

```text
keyboard-reachable primary actions
semantic labels for inputs/actions
visible focus
non-color-only status meaning
readable loading/error/empty states
```

This Gate does not freeze a full design system or theme engine.

## Proposed implementation slices

M3.5 may be implemented through sequential fixed-head Gates/PRs:

```text
M3.5.1  Product shell + authentication + navigation
M3.5.2  Workbench + ReviewCase surface
M3.5.3  Finding / Action collaboration surface
M3.5.4  Notification + Management + Reminder actions
M3.5.5  Product acceptance / responsive / final polish
```

These remain one M3.5 Product Surface architecture stage. Each slice keeps the established discipline:

```text
Gate
→ implementation
→ fixed head
→ review
```

## Explicit non-goals

M3.5 must not opportunistically add:

```text
drag-and-drop dashboards
custom homepages
theme system / theme builder
complex chart platform
WebSocket realtime collaboration
online co-editing
custom workflow builder
Scenario form designer
mobile native app
PWA offline mode
full internationalization framework
AI summaries
new Reminder cadence/scheduler infrastructure
new Review Core state or permission concepts
```

## Final architecture test

The M3.5 architecture succeeds when a developer unfamiliar with EasyAudit-Next internals can build and use the UI without being able to identify any frontend module that acts as the canonical source of business authorization, lifecycle, overdue, reminder-recipient, provenance, or task truth.

The Product Surface should make the established backend model easier to use, not create a competing model.