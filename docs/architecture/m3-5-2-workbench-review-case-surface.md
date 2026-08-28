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

with a real personal Workbench and ReviewCase context surface while preserving one authoritative business truth:

> **Workbench membership comes only from M3.1; ReviewCase lifecycle and visibility come only from Review Core/Scenario authorization; Product collections are bounded read-side projections over those existing facts; progress and overdue facts come only from approved server projections; React owns presentation, not business derivation.**

Conceptually:

```text
authenticated user
      ↓
GET /api/v1/me/workbench
      ↓
server-projected personal work
      ↓
open ReviewCase collection or original ReviewCase
      ↓
authorization-safe bounded ReviewCase Product collection
      or
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
render server-authorized business context
```

## Hard scope boundary

M3.5.2 includes only:

```text
Workbench presentation
authorization-safe bounded ReviewCase Product collection prerequisite
ReviewCase collection presentation
ReviewCase detail/context presentation
Case member read presentation + narrow display-identity enrichment
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
new ReviewCase truth or materialized product entity
new management aggregate
new Scenario backend semantics
migration/schema change
Case lifecycle mutations
Case creation/member mutation forms
organization-wide user directory for ordinary users
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

M3.5.2 consumes this response directly.

Forbidden implementation shape:

```text
GET broad Case/Finding/Action collections
        ↓
TypeScript role/lifecycle/deadline rules
        ↓
client-generated personal task list
```

No frontend/backend entity equivalent to `WorkItem`, `TodoTask`, `InboxTask`, or `AttentionTask` may be introduced.

### Workbench presentation groups

The UI may give the exact server categories action-oriented labels, for example:

```text
待我验证      → verification_queue
Finding 责任  → finding_responsibilities
Action 责任   → action_responsibilities
已逾期        → overdue
即将到期      → due_soon
我参与的审查  → case_responsibilities
```

Presentation-only section ordering, timestamp formatting, collapsing empty sections, sorting, and filtering are allowed. Membership must not change because React interpreted a role or lifecycle.

### Original-resource navigation

Workbench items are pointers only:

```text
Case    → /review-cases/:caseId
Finding → /findings/:findingId
Action  → /action-items/:actionItemId
```

Finding/Action destinations may remain honest M3.5.3 placeholders during this slice. No Workbench-specific detail aggregate is created.

## ReviewCase collection requires a bounded Product query

The Product Surface route remains:

```text
/review-cases
```

and its server contract remains in the ordinary ReviewCase namespace:

```http
GET /api/v1/review-cases?limit=50&offset=0
```

However, the current baseline implementation of `GET /api/v1/review-cases` is **not** approved for direct Product Surface use unchanged.

The baseline command-oriented path effectively performs:

```text
organization-wide ReviewCase list
        ↓
for every Case
    resolve ScenarioVersion / Scenario
    build per-Case authorization context
        CaseMember
        Findings
        FindingParticipants
    exact ScenarioPolicy VIEW_CASE
        ↓
visible list
```

That shape is correct enough for command-side correctness and small M2 flows, but M3.5.2 must not promote an organization-wide/per-Case traversal into a high-frequency top-level Product collection.

### Product collection invariant

M3.5.2 must introduce or refactor to an authorization-safe bounded read-side query over the existing Review Core facts:

```text
actor-scoped candidate relationship/resource facts
        ↓
bulk load authorization facts for the candidate set
        ↓
bulk resolve exact historical
(scenario_key, scenario_version)
        ↓
ScenarioPolicy.authorization.VIEW_CASE
        ↓
authorized Cases only
        ↓
stable server ordering
        ↓
pagination
        ↓
authorized total
```

The implementation shape may be a dedicated downstream query service or an equivalent read-oriented composition. It must not create a second `ReviewCase`, visibility table, WorkItem, materialized authorization truth, or Product-only lifecycle.

The query may read persistence records directly as a projection, following the M3.1/M3.3 precedent, while exact ScenarioPolicy remains the authorization authority.

### Candidate discovery must be authorization-complete

Candidate discovery is an optimization boundary, not a new authorization rule.

It must load a **superset of every Case that could be authorized for the current actor** from the relationship/actor facts already defined by the historical Scenario permission model. It may use bulk reverse lookups for current-user and applicable Department relationship facts, but it must not hard-code `process_review` role strings as the definition of visibility.

Correct shape:

```text
candidate discovery
→ may include extra candidates
→ exact historical ScenarioPolicy VIEW_CASE decides final visibility
```

Forbidden shape:

```text
role_key == "lead"
→ visible Case
```

or any candidate shortcut that can exclude a Case which the exact historical ScenarioPolicy would authorize.

### Organization-wide command traversal is forbidden for this collection

The Product collection must not use the unchanged baseline chain:

```text
ReviewCoreRepository.list_cases(organization)
        ↓
for each Case
    command-side _authorization_context()
        ↓
per-Case/per-Finding repository traversal
```

Likewise it must not introduce a logically equivalent N+1 implementation behind a new class name.

ScenarioVersion/Scenario records, Case relationship grants, Finding relationship grants, and any other permission-source facts required for the candidate set must be obtained in bounded/bulk query shapes rather than one query per Case/Finding.

This constraint applies to the collection path only. Existing single-resource command/detail authorization may remain unchanged where it is not used as the Product collection algorithm.

### Authorization must precede pagination

Raw SQL candidate pagination before authorization is forbidden:

```text
SQL candidates
→ LIMIT/OFFSET
→ Scenario authorization
```

because hidden rows would distort page membership and `total`.

The required semantic order is:

```text
candidate facts
→ bulk authorization context
→ exact historical ScenarioPolicy VIEW_CASE
→ authorized result set
→ stable order
→ offset/limit
```

The implementation may optimize this sequence internally, but externally observable page membership and `total` must be exactly equivalent to **authorization first, pagination second**.

### Bounded paging contract

M3.5.2 freezes the same basic paging discipline already used by M3.3:

```text
limit:  1..100
        default 50

offset: >= 0
```

The Product collection response must expose an envelope equivalent to:

```text
items
 total
 limit
 offset
```

where `total` is the count **after current-user authorization** and after any server filters that may later be explicitly added.

The default collection order is deterministic:

```text
created_at DESC
id DESC
```

or an implementation-equivalent stable server order with an explicit persisted-ID tie-breaker. React must not be required to reconstruct canonical paging order from an unbounded response.

M3.5.2 does not require search, lifecycle filters, plan filters, cursor pagination, or a new index/migration. If implementation evidence shows an index is truly required, that is a separate scope review because this Gate currently expects no migration.

### Collection presentation

React renders only the server-returned authorized page. Workbench membership, platform role, cached navigation state, or management scope must not broaden it.

The first page may display returned title, lifecycle, exact Scenario key/version, and planned timing. No client-computed canonical progress percentage is allowed.

`system_admin` remains only a platform role; it does not bypass Scenario business authorization for this collection.

## ReviewCase detail is a context container

The detail page begins with:

```http
GET /api/v1/review-cases/{case_id}
```

A successful Case GET establishes only current Case visibility. It does not imply management authority or mutation authority.

Recommended first structure:

```text
Case Header
├── title / lifecycle
├── exact Scenario version
├── plan timing
└── persisted timestamps

Sections
├── 概览
├── Findings
├── 成员
└── Activity
```

Generic Case fields come directly from `ReviewCaseResponse`, including:

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

React may format values but must not derive a competing lifecycle or deadline classification.

## Findings section on Case page

M3.5.2 may consume:

```http
GET /api/v1/review-cases/{case_id}/findings
```

only to show original Finding rows under the Case. Rows may render returned title, severity, lifecycle, raised_at and link to `/findings/:findingId`.

This slice does not implement Finding transitions, participants, rectification, verification, Action work, or Finding scenario editing.

The page must not recompute canonical Case closure/progress totals from the Finding list when approved server projections already own those facts.

## Members section and display identity prerequisite

The existing member relationship endpoint is:

```http
GET /api/v1/review-cases/{case_id}/members
```

Its baseline DTO contains relationship facts such as:

```text
case_id
user_id
role_key
joined_at
```

but no human-readable user identity. The only existing general user-list/detail API is system-admin-only and must not be reused by ordinary Product Surface users.

M3.5.2 may therefore add one narrow **Case-scoped display identity enrichment** to the authorized member read contract.

Required semantics:

```text
current user passes normal Case visibility
        ↓
server obtains CaseMember rows for that Case
        ↓
server resolves display identity only for those returned member user_ids
        ↓
member view includes display_name
```

This enrichment must not:

```text
open an organization-wide ordinary-user directory
call /api/v1/admin/users from React
make User identity a new Case authorization source
change CaseMember persistence
change role semantics
add member mutation behavior
```

The authoritative relationship remains `CaseMember`; `display_name` is only presentation identity for an already-returned member.

An additive `display_name` on the existing member response or an equivalent Case-scoped read DTO is acceptable. No migration is expected.

React may display role keys as relationship facts, but must not translate them into authority such as:

```ts
role_key === "lead" → canManage
```

## Management progress is optional and server-authorized

M3.3 exposes:

```http
GET /api/v1/management/review-cases/{case_id}/progress
```

Its authorization scope is intentionally narrower than ordinary `view_case`: the caller must satisfy exact historical Scenario management authorization, including existing `manage_case_members` capability.

Therefore the endpoint is never a prerequisite for rendering an otherwise visible Case.

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
         → omit / mark summary unavailable
         → Case remains visible
```

Forbidden:

```text
management progress 404
→ hide Case
```

and:

```text
management progress unavailable
→ recompute Finding/Action progress or overdue in TypeScript
```

When available, React may render returned deadline_bucket, Finding lifecycle counts, Action lifecycle counts, overdue counts and due-soon counts. No `overallProgress` or alternate overdue formula is introduced.

## Scenario UI registry becomes executable in M3.5.2

M3.5.2 is the first slice rendering Case `scenario_data`, so the M3.5 exact-version Scenario UI boundary must now exist in code.

Conceptually:

```text
ScenarioUiRegistry
    ↓ exact lookup
(scenario_key, scenario_version)

process_review@1
└── CaseScenarioSection
```

Generic Workbench/Case code must not contain distributed Scenario business branches.

### process_review@1 Case presentation

The first adapter may render the already-defined Case scenario fields:

```text
area_code
review_type
```

It is presentation-only and must not implement authorization, workflow legality, overdue, management scope, or reminder recipient logic.

### Exact-version fail closed

```text
(process_review, 1) → ProcessReviewV1 adapter
```

A resource such as `process_review@99` must not resolve to v1, latest, nearest, key-only, or another registered adapter.

Expected:

```text
generic Case fields
→ may render after server Case authorization

Scenario-specific section
→ explicit unsupported/unavailable exact-version state

Scenario-specific editing
→ unavailable
```

No low-code schema engine is required.

## Activity read prerequisite

The baseline persists append-only Review `Activity` facts and supports single-Activity persistence lookup, but exposes no Product Surface HTTP list/read route.

M3.5.2 may add exactly one narrow read-only prerequisite:

```http
GET /api/v1/review-cases/{case_id}/activities
```

Its purpose is only to render **ReviewCase-subject Activity** history on the Case page.

### Authorization order

The endpoint first establishes normal current ReviewCase visibility using the same business authorization semantics as ordinary Case read:

```text
BusinessIdentity
→ normal get/view ReviewCase authorization
→ only then query Case-subject Activity rows
```

Known foreign or unauthorized Case IDs preserve established non-disclosing behavior.

### Subject boundary

Returned rows are restricted to:

```text
organization_id = current organization
review_case_id = requested case
finding_id IS NULL
action_item_id IS NULL
submission_id IS NULL
```

The endpoint must not aggregate Finding-, ActionItem-, or Submission-subject Activity into a Case-wide timeline in this slice. Child visibility is target-specific; broad timeline aggregation could leak hidden resources in future Scenario versions.

Child Activity presentation belongs with the corresponding M3.5.3 resource surface and authorization.

### Activity DTO

The first M3.5.2 Activity DTO is deliberately metadata-free:

```text
id
subject_type = review_case
subject_id = case_id
event_type
actor_id
occurred_at
```

`Activity.metadata` is not required for M3.5.2 and must not be exposed merely for frontend convenience. A later need to surface event metadata requires explicit field-by-field privacy review.

The implementation must not invent a second event taxonomy or transform Activity into Notification truth.

Ordering is deterministic by `occurred_at` plus stable Activity ID tie-breaker. No Activity mutation endpoint is added.

### Implementation placement

The list/read path should be downstream/read-oriented. A small query service/API may read `ActivityRecord` directly after normal Case authorization.

M3.5.2 does not require expanding `ReviewCoreRepository` into a generic timeline/query repository merely to serve React.

No migration is expected because Activity already exists.

## Case mutations are not part of M3.5.2

The backend already has Case command endpoints, but the Product Surface has no server-owned affordance projection such as typed `allowed_actions`.

M3.5.2 therefore remains read/navigation oriented and must not hard-code Process Review lifecycle/role matrices in React just to choose transition buttons.

Case lifecycle mutation, Case creation, and Case member mutation require a later explicitly reviewed Product Surface increment if exposed.

This is a Product Surface scope boundary, not a change to backend capabilities.

## Shared API boundary

All requests continue through the M3.5.1 shared API transport. Feature code must not scatter raw `fetch()` calls.

M3.5.2 may add wire DTOs for:

```text
WorkbenchResponse
ReviewCaseCollectionResponse
ReviewCaseResponse
CaseMemberViewResponse
FindingResponse
ManagementCaseProgressResponse
ReviewCaseActivityResponse
```

These are transport representations only, not a second TypeScript business domain.

## Data freshness and cache boundary

M3.5.2 may use a small query abstraction/cache, but server data remains authoritative.

If a cache is introduced:

- it is cache, not authorization or business truth;
- protected entries clear/become inaccessible on logout, Session expiry, and user change;
- cached Workbench membership never grants Case access;
- opening a Workbench link always re-enters current resource authorization;
- no protected business cache persists in localStorage/sessionStorage.

## Current authorization after Workbench navigation

Required counterexample:

```text
T0 User has relationship
→ Workbench includes Case

T1 relationship changes on server

T2 user opens old Workbench link
→ normal GET /review-cases/{id}
→ server current authorization decides
```

If access is now refused/non-disclosing, the Case page must not reveal title, lifecycle, scenario_data, member identities, Findings, progress, or Activity from stale Workbench data.

## Loading / empty / error behavior

Workbench and Case pages must explicitly support:

```text
loading
empty
request error
not found / no current access
session expiry
optional progress unavailable
unsupported Scenario UI version
```

A failed subordinate/optional request must not cause unrelated sections to fabricate fallback truth.

## Responsive and accessibility baseline

M3.5.5 owns final Product responsive Acceptance, but M3.5.2 must not regress M3.5.1.

Workbench and ReviewCase viewing must remain usable at common desktop/laptop and narrow mobile widths. Core links/sections must be keyboard reachable, statuses must have text meaning beyond color, and loading/error/empty states must be readable.

## Implementation increments after Gate PASS

Recommended executable sequence:

```text
1. authorization-safe bounded ReviewCase collection read prerequisite + wire DTOs
2. Workbench real server projection surface
3. ReviewCase collection + generic detail shell
4. exact Scenario UI registry + process_review@1 Case adapter
5. member display-identity enrichment + Findings composition
6. narrow ReviewCase Activity read prerequisite + Activity section
7. optional server-authorized management progress summary
8. unit/component + PostgreSQL query-shape + real browser Acceptance
9. exact-head CI + Final Review
```

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

M3.5.2 is complete when an authenticated user can use the actual M3.1 Workbench projection, browse a bounded/paginated ReviewCase collection whose membership and total are computed by exact current Scenario authorization before pagination, navigate into a currently authorized ReviewCase, read generic Case facts, exact-version Scenario presentation, human-readable Case member identities inside the authorized Case scope, visible Findings, metadata-free Case-subject Activity history, and any optional management progress the server currently authorizes—without organization-wide per-Case collection traversal or React reconstructing work membership, lifecycle, deadline, progress, management scope, authorization, or organization user-directory access.
