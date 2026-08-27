# M3.5 Acceptance Gate — Product Surface

This document is the first M3.5 Architecture & Acceptance Gate. It freezes product-surface boundaries before large-scale React implementation is allowed.

The Gate branch starts from:

```text
main@abf7801f336aa13634098d266defd2cd921dbdf5
```

The PR introducing this Gate must remain **Draft / open / unmerged** during architecture review.

The first Gate is documentation-only. It must not add React implementation, frontend dependencies, backend affordance APIs, Review Core changes, Notification schema changes, Reminder cadence/scheduler infrastructure, or migrations.

M3.5 implementation begins only after this contract is explicitly accepted.

## Scope proof

The first design PR must contain only:

```text
docs/architecture/m3-5-product-surface.md
docs/architecture/m3-5-acceptance.md
```

Any executable source, migration, package manifest, CI workflow, or API-contract change is out of scope for the initial Gate unless separately reviewed.

## Baseline preservation

Acceptance requires M3.5 to preserve merged M2 and M3.1–M3.4 semantics.

Hard regressions include:

- changing ReviewCase/Finding/ActionItem lifecycle or transition rules;
- changing Scenario authorization semantics for UI convenience;
- changing Workbench membership/query truth;
- changing M3.3 overdue/progress definitions;
- changing Notification provenance/read semantics;
- changing M3.4 recipient responsibility or nudge semantics;
- introducing a generic Finding deadline;
- granting `system_admin` a frontend-only business bypass; or
- making a UI route/detail object a new business aggregate.

## Frontend truth boundary

Code review and tests must be able to prove that frontend code does not become authoritative for:

```text
authorization
lifecycle transition legality
overdue status
reminder/nudge recipients
historical Notification provenance
current responsibility
task/work ownership
```

A frontend branch equivalent to:

```ts
user.role === "reviewer" && finding.lifecycle === "verifying"
```

may only be a presentation hint. The backend command must independently authorize and validate the operation.

Acceptance fails if a business mutation succeeds or becomes reachable solely because TypeScript decided it was allowed.

## No second Workbench truth

The product Workbench must consume M3.1's Workbench API/read model.

Acceptance must reject an implementation that separately loads ReviewCase/Finding/ActionItem collections and reconstructs personal work membership using frontend role/lifecycle rules.

Required behavior:

- rendered Workbench membership matches the server projection;
- Workbench grouping/filtering remains presentation-only;
- every item navigates to the original business resource; and
- no `WorkItem`, `TodoTask`, `InboxTask`, or equivalent frontend/backend entity is introduced.

## Product shell / navigation acceptance

The first shell must make these primary areas available without creating additional domain semantics:

```text
我的工作
审查活动
通知
管理视图
管理设置
```

The default authenticated landing route is `/me/workbench`.

Acceptance must prove ordinary users can reach their assigned work without first entering a management dashboard.

Route guards may protect authentication/navigation UX but do not replace backend authorization.

## ReviewCase surface acceptance

The Case surface must render server-owned Case state and aggregate facts without inventing new progress truth.

Acceptance must reject:

- a frontend-computed canonical `overallProgress` percentage without an approved backend contract;
- lifecycle mutation through ordinary edit forms;
- Case-level data that bypasses existing resource visibility; and
- a Case-local second Finding/Action status model.

The page should compose existing facts for:

```text
Case lifecycle
plan timing
Finding closure state
Action completion state
overdue counts
members
Activity history
```

## Finding surface acceptance

The Finding surface must make the full collaboration context usable while retaining backend truth.

Acceptance must prove:

- title/lifecycle/severity/responsibility are rendered from server data;
- Scenario-specific data is rendered only through the approved Scenario UI extension boundary;
- participants, Actions, Submissions/Evidence, and Activity remain original backend resources;
- lifecycle actions call existing command endpoints; and
- stale or unauthorized actions are handled using authoritative backend errors/refetch rather than local override.

## ActionItem surface acceptance

Acceptance must prove ActionItem remains a rectification action and does not acquire a second verification workflow.

Forbidden additions include frontend or backend states equivalent to:

```text
action.approved
action.rejected
action.pending_review
```

unless a future Review Core architecture change explicitly introduces them.

The first UI may present assignment, due time, execution state, completion, and Evidence only from existing semantics.

## Notification Center acceptance

The product must treat Notification as persistent delivery history.

Acceptance must prove:

- unread/all views consume M3.2 records;
- marking read changes only Notification read state as already defined;
- a Notification click navigates to the original subject rather than granting access through Notification ownership;
- historical Notification receipt does not expose a currently unauthorized subject;
- `read_at` does not mutate Review Activity, lifecycle, Workbench, Management, or Reminder truth; and
- Notification is not reimplemented as transient toast history.

## Management acceptance

The Management UI consumes M3.3 read-side facts.

Acceptance must reject:

```text
ManagementIssue
SupervisionRecord
ExceptionTicket
ManagementTask
```

or any equivalent second management workflow.

Required behavior:

- rows/cards are observational projections;
- abnormal/overdue items navigate to original ReviewCase/Finding/ActionItem resources;
- management filters/sorts do not redefine backend overdue predicates; and
- any nudge shortcut invokes existing M3.4 subject commands rather than mutating Management state.

## Reminder / nudge UI acceptance

The first Product Surface may expose manual nudge only for subjects supported by M3.4:

```text
Finding
ActionItem
```

Acceptance must prove:

- the client does not submit arbitrary recipient User IDs;
- the UI does not hard-code `owner`, `primary`, `collaborator`, `lead`, or permission names as recipient truth;
- success produces the existing M3.4 delivery behavior;
- zero-recipient/unauthorized/stale cases surface the backend result safely; and
- no cadence, next-run, snooze, escalation, quiet-hour, or Reminder lifecycle UI is added.

ReviewCase manual nudge remains unavailable unless backend semantics are separately added later.

## Scenario UI extension boundary acceptance

A centralized Scenario UI extension point is a hard M3.5 requirement.

Before scenario-specific React implementation is accepted, code structure must establish one explicit boundary equivalent to:

```text
ScenarioUiRegistry
  └── exact scenario key/version -> typed adapter
```

Acceptance must prove:

1. generic Workbench/Case/Finding/Action/Notification/Management pages do not contain distributed `scenarioKey === "process_review"` business branches;
2. `process_review@1` UI differences live in one Scenario UI adapter/module or equivalent centralized registration boundary;
3. adapter lookup can distinguish exact Scenario versions when presentation semantics differ;
4. adding a test/second Scenario adapter does not require edits across many generic feature pages; and
5. adapters render Scenario-specific fields/content only and do not decide authorization, lifecycle, overdue, recipient, or provenance truth.

A test Scenario with intentionally different labels/field presentation should be sufficient to expose hard-coded Process Review assumptions without requiring a full second business Scenario implementation.

## No low-code engine requirement

Acceptance must not require or reward creation of:

```text
universal form builder
workflow designer
runtime entity designer
drag/drop schema editor
```

A minimal typed Scenario UI registry is valid and preferred until real multi-Scenario requirements prove otherwise.

## API consumption acceptance

All Product Surface business data/mutations must pass through one shared client boundary.

Acceptance should prove:

- authenticated transport is centralized;
- wire DTOs are consistent with OpenAPI/backend schemas;
- feature modules do not accumulate incompatible handwritten copies of the same resource schema;
- timezone-aware timestamps are parsed/displayed consistently;
- standard HTTP/business errors are mapped consistently; and
- successful mutations trigger defined invalidation/refetch of affected server data.

Generated OpenAPI TypeScript types/client are preferred but not an absolute first-slice requirement. Any handwritten wire types remain transport representations, not a second business domain model.

## Backend error authority acceptance

The UI must handle existing authoritative failure classes rather than pre-empting them with client truth.

Required cases include:

```text
unauthenticated/session expired
unauthorized or non-disclosing missing resource
409 concurrency/state conflict
422 validation/business input error where applicable
```

For stale mutation conflicts, Acceptance must prove the UI can:

```text
show conflict/error
→ refresh authoritative resource/query state
→ avoid blind semantic retry
```

A stale locally rendered state must never override a backend conflict.

## Authentication acceptance

The Product Surface consumes the existing server authentication/session contract.

Acceptance must prove:

- protected routes do not expose protected data before session resolution;
- session expiration returns to safe authentication UX;
- logout clears client caches containing protected resource data;
- no parallel frontend JWT/token model is invented without backend architecture review; and
- cached user/platform metadata is never treated as sufficient business authorization.

## Current-resource authorization after Notification/Workbench navigation

Deep links from Workbench, Notification, and Management must re-enter normal backend resource authorization.

Acceptance must include at least one case where:

```text
user historically received/owned item
→ relationship later changes
→ old Notification/Workbench link is opened
→ backend current authorization refuses or limits access
```

The frontend must not reveal hidden resource details from cached list data after authoritative access is lost.

## Current-state freshness acceptance

M3.5 must expect multi-user changes.

At minimum one test/user-flow must prove:

```text
actor A renders resource at T0
actor B changes lifecycle/assignment at T1
actor A submits stale command at T2
backend refuses or resolves according to existing concurrency rules
actor A UI refreshes to authoritative state
```

No client-side shadow lifecycle may silently win.

## Presentation-state allowance

The following local state is explicitly acceptable and is not considered business truth:

```text
selected tab
modal/drawer visibility
filters
sort/pagination presentation
expanded rows
unsaved form input
loading/error/empty state
```

Acceptance should distinguish normal UI state from forbidden domain truth duplication.

## Responsive acceptance

M3.5.5 Final Product Acceptance must verify the critical journey at common desktop/laptop size and at a narrow mobile browser width.

This does not require a native app or offline PWA.

Critical actions must remain reachable without horizontal-layout failure, including:

```text
Workbench navigation
Finding review/rectification actions
Action completion
Notification navigation
manual nudge where authorized
```

## Accessibility acceptance

The final surface must include at least basic accessibility checks for:

```text
keyboard reachability of primary actions
visible focus
input/action labels
status meaning not conveyed by color alone
readable loading/error/empty states
```

A complete design-system accessibility program is outside M3.5 scope.

## Final user journey

M3.5 Final Acceptance must exercise a real multi-user flow through the Web product:

```text
Lead logs in
→ Workbench shows led ReviewCase
→ opens Case
→ sees Finding/Action progress

Owner logs in
→ Workbench shows rectification responsibility
→ opens Finding
→ creates/completes Action work
→ submits Finding for verification

Reviewer logs in
→ Workbench shows verification work
→ opens Finding
→ rejects

Owner rectifies again
→ submits again

Reviewer approves
→ Finding closes

Lead opens Case / Management
→ sees closed Finding reflected in server-owned projections

If an eligible overdue target exists:
Lead invokes manual nudge
→ M3.4 resolves recipients
→ Owner receives persistent Notification
→ Notification navigation re-enters original target authorization
```

The exact fixture may use existing API capabilities, but the journey must run through the actual Product Surface rather than API-only acceptance.

## Final invariant checklist

M3.5 cannot pass Final Review unless all are true:

```text
no second WorkItem/task truth
no second lifecycle
no second overdue rule
no distributed frontend Scenario business branching
no system_admin business bypass
no Notification-as-capability access
no client-selected nudge recipients
no Action verification lifecycle invented by UI
no Management write-side domain
no Reminder cadence/scheduler scope creep
all mutations still use existing backend APIs/policies
all historical Notification provenance remains backend-owned and traceable
```

## Proposed fixed-head sequence

Recommended implementation order:

```text
M3.5.1  Product shell + authentication + navigation
M3.5.2  Workbench + ReviewCase surface
M3.5.3  Finding / Action collaboration surface
M3.5.4  Notification + Management + Reminder actions
M3.5.5  Product acceptance / responsive / final polish
```

Each slice requires its own implementation fixed head, CI evidence, and review before proceeding.

## Explicit non-goals

M3.5 Acceptance excludes:

```text
drag-and-drop dashboards
custom homepages
theme builder
complex chart platform
WebSocket realtime collaboration
online co-editing
custom workflow builder
Scenario form designer
native mobile app
PWA offline mode
full internationalization framework
AI summaries
resident scheduler/cadence policy
new Review Core semantics
```

The M3.5 Product Surface succeeds when users can complete the established EasyAudit-Next business loop through the UI while every important business decision remains authoritative in the already-frozen backend layers.