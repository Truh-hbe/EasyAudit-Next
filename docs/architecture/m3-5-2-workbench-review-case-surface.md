# M3.5.2 — Workbench & ReviewCase Surface Gate

M3.5.2 begins only after M3.5.1 Product Shell / Authentication / Navigation is merged and frozen.

Baseline:

```text
main@d97af2475df5b018828e18f49ba4ee718a983a6f
```

Fixed upstream references:

```text
M3.5 Product Surface Architecture Gate:
d19c897468fe1c179c939a59b8fd38f69c7c87c1

M3.5.1 Product Shell Final Review fixed head:
51ad3987f4eabb0eb2c689cf0ce0073f7591a569

M3.5.1 merge commit / current baseline:
d97af2475df5b018828e18f49ba4ee718a983a6f
```

This Gate is design-only. It freezes the M3.5.2 product/read-contract boundary before executable Workbench and ReviewCase UI is added.

It must not add React implementation, backend executable code, migrations, Review Core lifecycle changes, new business permissions, Notification/Reminder behavior, or M3.5.3 Finding/Action collaboration mutations.

## Goal

M3.5.2 replaces the M3.5.1 placeholders for:

```text
/me/workbench
/review-cases
/review-cases/:caseId
```

with a real personal Workbench and a real ReviewCase context surface while preserving one authoritative business truth:

> **Workbench membership comes only from M3.1; ReviewCase lifecycle and visibility come only from Review Core/Scenario authorization; progress and overdue facts come only from approved server projections; React owns presentation, not business derivation.**

The main user loop for this slice is:

```text
authenticated user
      ↓
GET /api/v1/me/workbench
      ↓
see server-projected personal responsibilities / time risk
      ↓
open original ReviewCase
      ↓
GET /api/v1/review-cases/{case_id}
      +
GET /api/v1/review-cases/{case_id}/members
      +
GET /api/v1/review-cases/{case_id}/findings
      +
optional authorized management progress
      +
Case-subject Activity history read contract
      ↓
render one business-context page
```

## Hard scope boundary

M3.5.2 includes only:

```text
Workbench presentation
ReviewCase collection presentation
ReviewCase detail/context presentation
Case members read presentation
Case Finding summary/list presentation
exact Scenario UI registry for Case scenario_data
optional server-authorized Case management progress summary
narrow read-only ReviewCase-subject Activity API prerequisite
loading / empty / error / stale-safe refresh behavior
real browser Acceptance for the above
```

Explicitly out of scope:

```text
Finding detail/collaboration implementation
ActionItem detail/collaboration implementation
Finding/Action mutations
Notification Center
Management dashboard UI
manual nudge UI
new lifecycle states
new business permissions
new overdue/deadline rules
new WorkItem/Todo entity
new management aggregate
new Scenario backend semantics
migration/schema change
Case lifecycle mutations unless separately approved by a later Gate
Case creation/member mutation forms unless separately approved
full child-resource Activity timeline
```

M3.5.3 remains responsible for Finding / Action collaboration surfaces. M3.5.4 remains responsible for Notification / Management / Reminder product surfaces.

## No second Workbench truth

The authoritative personal projection already exists:

```http
GET /api/v1/me/workbench
```

with server-owned response categories:

```text
case_responsibilities
finding_responsibilities
action_responsibilities
verification_queue
due_soon.cases
due_soon.actions
overdue.cases
overdue.actions
as_of
```

M3.5.2 must consume this response directly.

Forbidden implementation shape:

```text
GET /review-cases
GET /findings
GET /action-items
        ↓
TypeScript role/lifecycle/deadline rules
        ↓
client-generated personal task list
```

No frontend/backend entity equivalent to:

```text
WorkItem
TodoTask
InboxTask
AttentionTask
```

may be introduced.

### Workbench presentation groups

The first UI may present the exact server categories with action-oriented labels such as:

```text
待我验证
→ verification_queue

Finding 责任
→ finding_responsibilities

Action 责任
→ action_responsibilities

已逾期
→ overdue

即将到期
→ due_soon

我参与的审查
→ case_responsibilities
```

The UI may reorder sections, format timestamps, collapse empty sections, or provide presentation-only filtering/sorting.

It must not change membership by interpreting role strings or lifecycle enums.

### Original-resource navigation

Workbench items are pointers only:

```text
Case item
→ /review-cases/:caseId

Finding item
→ /findings/:findingId

Action item
→ /action-items/:actionItemId
```

During M3.5.2, Finding/Action routes may remain honest M3.5.3 placeholders after navigation. They must not create a second Workbench detail domain.

## ReviewCase collection surface

`/review-cases` consumes the existing authorized:

```http
GET /api/v1/review-cases
```

The UI renders the returned ReviewCase resources; it does not broaden visibility using Workbench membership, platform role, cached navigation state, or management scope.

The first collection may display:

```text
title
lifecycle
scenario_key + scenario_version presentation
planned_start_at / planned_end_at
```

and navigate to `/review-cases/:caseId`.

No client-computed canonical progress percentage is allowed.

## ReviewCase detail is a context container

The detail page must begin with the ordinary business resource contract:

```http
GET /api/v1/review-cases/{case_id}
```

A successful Case GET establishes only that the current server authorization allows this Case to be rendered. It does not imply management authority or mutation authority.

Recommended first structure:

```text
Case Header
├── title
├── lifecycle
├── exact Scenario version
├── plan timing
└── persisted Case timestamps

Sections
├── 概览
├── Findings
├── 成员
└── Activity
```

### Generic Case facts

Generic Case fields come directly from `ReviewCaseResponse`:

```text
id
plan_id
scenario_key
scenario_version
title
lifecycle
planned_start_at
planned_end_at
started_at
fieldwork_completed_at
closed_at
created_at
scenario_data
```

The UI may format values but must not derive a competing lifecycle or deadline classification.

## Findings section on Case page

M3.5.2 may consume:

```http
GET /api/v1/review-cases/{case_id}/findings
```

only to show original Finding rows under the Case.

Each row may show returned fields such as:

```text
title
severity
lifecycle
raised_at
```

and link to `/findings/:findingId`.

M3.5.2 must not implement Finding transitions, participants, rectification, verification, Action work, or Finding scenario editing. Those are M3.5.3 scope.

A Case page must not recompute canonical closure/progress totals from this list when an approved server projection already owns those facts.

## Members section

M3.5.2 consumes:

```http
GET /api/v1/review-cases/{case_id}/members
```

as an original server resource list.

The first surface is read-only. Role keys may be rendered as returned relationship facts, but React must not translate them into authorization decisions such as:

```ts
role_key === "lead" → canManage
```

Member mutation is outside this Gate.

## Management progress is optional and server-authorized

M3.3 exposes:

```http
GET /api/v1/management/review-cases/{case_id}/progress
```

but its authorization scope is intentionally narrower than ordinary `view_case`: the caller must satisfy exact historical Scenario management authorization, including the existing `manage_case_members` capability.

Therefore M3.5.2 must never make this endpoint a prerequisite for rendering an otherwise visible Case.

Correct composition:

```text
ordinary Case GET = 200
        ↓
render Case
        ↓
optional management progress request
    ├── 200
    │    → render server-owned factual progress/deadline summary
    └── non-disclosing 404
         → omit / mark management summary unavailable
         → Case remains visible
```

Forbidden behavior:

```text
management progress 404
→ infer current user is unauthorized for Case
→ hide Case
```

or:

```text
management progress unavailable
→ recompute Finding/Action overdue and progress in TypeScript
```

### Server-owned progress facts

When the optional endpoint succeeds, React may render only returned facts, including:

```text
Case deadline_bucket
Finding lifecycle counts
Action lifecycle counts
Action overdue count
Action due-soon count
```

No `overallProgress` percentage or alternate overdue formula is introduced.

## Scenario UI registry becomes executable in M3.5.2

M3.5.2 is the first slice that renders Case `scenario_data`; therefore the M3.5 exact-version Scenario UI boundary must now exist in code.

Conceptual structure:

```text
ScenarioUiRegistry
    ↓ exact lookup
(scenario_key, scenario_version)

process_review@1
└── CaseScenarioSection
```

The physical paths may differ, but generic Workbench/Case code must not own distributed Scenario branching.

### process_review@1 Case presentation

The first adapter may render the already-defined Case scenario fields:

```text
area_code
review_type
```

with user-facing labels/grouping.

This adapter is presentation-only. It must not implement:

```text
canTransitionCase()
canManageMembers()
isCaseOverdue()
allowedActions()
reminder recipients
```

### Exact-version fail closed

Registry lookup is exact:

```text
(process_review, 1) → ProcessReviewV1 adapter
```

A resource such as:

```text
process_review@99
```

must not resolve to `process_review@1`, latest, nearest, key-only, or a default Scenario-specific renderer.

Expected behavior:

```text
generic Case fields
→ render when server Case authorization succeeds

Scenario-specific section
→ explicit unsupported/unavailable exact-version state

Scenario-specific editing
→ unavailable
```

M3.5.2 does not require a low-code schema engine.

## Activity read prerequisite

The current baseline persists append-only Review `Activity` facts but exposes no HTTP read endpoint for the Product Surface.

M3.5.2 may therefore add exactly one narrow read-only prerequisite:

```http
GET /api/v1/review-cases/{case_id}/activities
```

Its purpose is only to render ReviewCase-subject Activity history on the Case page.

### Authorization order

The Activity endpoint must first establish normal current ReviewCase visibility using the same business authorization semantics as the ordinary Case read.

Conceptually:

```text
current BusinessIdentity
        ↓
normal get/view ReviewCase authorization
        ↓
only if authorized:
query Activity rows
```

Known foreign/unauthorized Case IDs must preserve the established non-disclosing behavior.

### Subject boundary

M3.5.2 Activity read scope is deliberately restricted to:

```text
Activity.organization_id = current organization
Activity.subject_type = review_case
Activity.review_case_id / subject_id = requested case
```

It must not aggregate Finding-, ActionItem-, or Submission-subject activities into a Case-wide timeline in this slice.

Reason: child visibility is target-specific and future Scenarios may allow Case access while hiding child resources. A broad timeline could leak hidden Finding/Action facts.

Child Activity presentation belongs with the corresponding M3.5.3 resource surface and authorization.

### Activity DTO

The Product Surface may consume a thin wire representation of existing immutable facts, for example:

```text
id
subject_type
subject_id
event_type
actor_id
occurred_at
payload / metadata only if already safe for this subject
```

The implementation must not invent a second event taxonomy or transform Activity into Notification truth.

Ordering must be deterministic, newest-first or oldest-first with stable Activity ID tie-breaker; the chosen order is presentation/read-contract semantics only.

No Activity mutation endpoint is added.

### Implementation placement

The read path should be downstream/read-oriented rather than expanding mutation semantics for frontend convenience.

Acceptable implementation shapes include a small dedicated query service/API that reads `ActivityRecord` directly after normal Case authorization.

This Gate does not require adding generic management/query methods to `ReviewCoreRepository` merely to serve React.

No migration is expected because Activity already exists.

## Case mutations are not part of M3.5.2

The baseline has existing Case command endpoints, but the Product Surface does not yet have a server-owned affordance projection such as typed `allowed_actions`.

M3.5.2 therefore deliberately remains a read/navigation slice.

It must not hard-code Process Review lifecycle/role matrices in React merely to choose Case transition buttons.

Case lifecycle mutation, Case creation, and Case member mutation require a later explicitly reviewed Product Surface increment if they are to be exposed.

This is a scope boundary, not a change to backend capabilities.

## Shared API boundary

All requests continue through the M3.5.1 shared API transport.

Feature code must not scatter raw `fetch()` calls.

M3.5.2 may add direct wire DTOs for:

```text
WorkbenchResponse
ReviewCaseResponse
CaseMemberResponse
FindingResponse
ManagementCaseProgressResponse
ReviewCaseActivityResponse
```

These are transport representations only.

No TypeScript domain model may redefine lifecycle, authorization, deadline, or work membership.

## Data freshness and cache boundary

M3.5.2 may use a small request/query abstraction, but server data remains authoritative.

If a query cache is introduced:

- it is cache, not business truth;
- protected resource caches must clear on logout/session expiry/user change;
- successful future mutations must invalidate affected queries;
- a cached Workbench item never grants access to a Case;
- opening an item always re-enters the original resource authorization.

No persistent protected business cache in localStorage/sessionStorage.

## Current authorization after Workbench navigation

Historical/cached Workbench visibility does not grant current resource access.

Required shape:

```text
T0 User has relationship
→ Workbench includes Case
→ relationship later changes at server
→ user opens old Workbench link
→ normal GET /review-cases/{id}
→ server current authorization decides
```

If access is now refused/non-disclosing, the Case page must not reveal title, lifecycle, scenario_data, members, Findings, or progress from stale Workbench data.

The UI may show a safe unavailable/not-found state and refresh/remove stale Workbench presentation.

## Loading / empty / error behavior

Workbench and Case pages must have explicit states for:

```text
loading
empty
request error
not found / no current access
session expiry
optional progress unavailable
unsupported Scenario UI version
```

A rejected child/optional request must not cause unrelated already-authorized sections to fabricate fallback truth.

## Responsive and accessibility baseline

M3.5.5 owns final Product responsive Acceptance, but M3.5.2 must not regress the M3.5.1 responsive shell.

At minimum Workbench and ReviewCase viewing must remain usable at:

```text
common desktop/laptop width
narrow mobile browser width
```

Core links/sections must remain keyboard reachable, status meaning must include text rather than color alone, and loading/error/empty states must be readable.

## Implementation increments after Gate PASS

Recommended executable sequence:

```text
1. wire DTOs + feature API boundary
2. Workbench real server projection surface
3. ReviewCase collection + generic detail shell
4. exact Scenario UI registry + process_review@1 Case adapter
5. members + Finding list composition
6. narrow ReviewCase Activity read prerequisite + Activity section
7. optional server-authorized management progress summary
8. unit/component + real browser Acceptance
9. exact-head CI + Final Review
```

The implementation PR may combine commits differently, but each semantic boundary must remain reviewable.

## No M3.5.3 / M3.5.4 leakage

M3.5.2 must not add:

```text
Finding transition buttons
Action completion/start/cancel UI
Submission/Evidence forms
Notification inbox/read UI
management collection/dashboard
nudge button
recipient selection
reminder cadence
```

Navigation to later resource routes may exist, but content remains an honest future-slice placeholder until the corresponding Gate is approved.

## End state

M3.5.2 is complete when an authenticated user can use the actual M3.1 Workbench projection, navigate into a currently authorized ReviewCase, read generic Case facts, exact-version Scenario presentation, members, visible Findings, Case-subject Activity history, and any optional management progress the server currently authorizes—without React reconstructing work membership, lifecycle, deadline, progress, management scope, or authorization.
