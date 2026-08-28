# M3.5.2 Acceptance Gate — Workbench & ReviewCase Surface

This Acceptance Gate freezes the executable proof required before M3.5.2 may pass Final Review.

Baseline:

```text
main@d97af2475df5b018828e18f49ba4ee718a983a6f
```

The Gate PR itself is documentation-only and must remain Draft / open / unmerged during review.

## Gate PR scope proof

Before implementation is unlocked, this Gate PR must contain only:

```text
docs/architecture/m3-5-2-workbench-review-case-surface.md
docs/architecture/m3-5-2-acceptance.md
```

Any `web/**`, backend executable source, migration, package/lockfile, or CI change is forbidden before Gate approval.

## Upstream preservation

M3.5.2 must preserve all frozen M3.5.1 security/session behavior:

```text
resolving / anonymous / authenticated Session model
server-owned must_change_password posture
same-origin /api/v1/* transport
Secure HttpOnly SameSite=Strict cookie
central Session 401 handling
internal-only intended routes
cross-user protected-state isolation
```

It must also preserve M3.1/M3.3 truth ownership:

```text
Workbench membership = M3.1 server projection
management scope/progress/overdue = M3.3 server projection
ReviewCase visibility/lifecycle = Review Core + exact Scenario authorization
ReviewCase Product collection = bounded read projection over those same facts
```

## No-second-Workbench acceptance

Executable tests must prove `/me/workbench` is populated from:

```http
GET /api/v1/me/workbench
```

and is not reconstructed from broad Case/Finding/Action collections.

A valid fixture should contain multiple distinct server categories, for example:

```text
case_responsibilities
finding_responsibilities
action_responsibilities
verification_queue
due_soon
overdue
```

Rendered membership must match the server response even where role/lifecycle combinations would tempt client inference.

Acceptance fails for logic equivalent to:

```ts
if (case.role === "lead") work.push(case)
if (finding.lifecycle === "verifying") verification.push(finding)
if (action.dueAt < Date.now()) overdue.push(action)
```

Presentation grouping, labels, sorting/filtering and empty-state choices remain allowed.

## Original-resource navigation

Tests must prove server-projected items navigate to original identities:

```text
Case    → /review-cases/:caseId
Finding → /findings/:findingId
Action  → /action-items/:actionItemId
```

No Workbench item gets an independent lifecycle or detail aggregate. Finding/Action destinations may remain explicit M3.5.3 placeholders.

## Stale Workbench link authorization counterexample

A real backend/browser Acceptance must cover:

```text
T0
User A has current relationship
→ /me/workbench includes Case C

T1
server-side relationship changes/removes A's current access

T2
A follows old Workbench link to /review-cases/C
→ browser performs normal current Case GET
→ backend refuses/non-discloses current access
→ no Case detail is rendered from stale Workbench data
```

After refusal the browser must not reveal stale:

```text
Case title
lifecycle
scenario_data
member identities
Findings
management progress
Activity
```

A stale Workbench pointer is never a capability token.

## ReviewCase Product collection acceptance

The M3.5.2 `/review-cases` Product Surface must not directly use the baseline organization-wide command-oriented list traversal unchanged.

The Product contract is bounded and paginated:

```http
GET /api/v1/review-cases?limit=50&offset=0
```

with paging discipline:

```text
limit:  1..100, default 50
offset: >= 0
```

and a response envelope equivalent to:

```text
items
total
limit
offset
```

`total` is the authorized result count before page slicing, and after any explicitly supported server filters.

### Authorization-before-pagination invariant

The executable query must be semantically equivalent to:

```text
candidate facts
        ↓
bulk authorization context
        ↓
exact historical
(scenario_key, scenario_version)
        ↓
ScenarioPolicy VIEW_CASE
        ↓
authorized results
        ↓
stable server order
        ↓
offset / limit
```

The following is forbidden:

```text
SQL raw candidates
→ LIMIT/OFFSET
→ authorization
```

because hidden rows must never distort page membership or `total`.

### Hidden-candidate pagination counterexample

A PostgreSQL integration test must include ordered candidates equivalent to:

```text
A / H1 / B / H2 / C
```

where:

```text
A, B, C = visible to User U
H1, H2 = not visible to User U
```

With `limit=2`, expected authorized paging is:

```text
page 1: A, B
page 2: C
total:  3
```

not:

```text
page 1: A
page 2: B
```

or any other result polluted by hidden rows occupying raw SQL page slots.

Insert additional hidden candidates before/between visible Cases and repeat. Visible page membership and authorized `total` must remain unchanged apart from explicitly documented stable-order effects of visible rows themselves.

### Stable-order proof

The Product collection must use deterministic persisted ordering. The default contract is:

```text
created_at DESC
id DESC
```

or an implementation-equivalent documented server order with a persisted-ID tie-breaker.

Tests must include equal `created_at` values and prove repeated requests return stable page membership.

### Candidate completeness proof

Candidate discovery is not authority. It may narrow database work only if it is a superset of every Case the exact historical ScenarioPolicy could authorize for the actor.

Tests/source review must reject shortcuts equivalent to:

```text
role_key == "lead" → visible
```

or a Process Review-specific role whitelist used as final visibility truth.

At least one fixture must demonstrate that candidate discovery is followed by exact `(scenario_key, scenario_version)` policy authorization rather than role-string inference.

### No organization-wide per-Case traversal

Source review must reject the unchanged baseline collection shape:

```text
ReviewCoreRepository.list_cases(organization)
        ↓
for each Case
    command-side _authorization_context()
        ↓
per-Case/per-Finding repository queries
```

and any renamed equivalent.

The Product query must bulk-load candidate Cases, exact ScenarioVersion/Scenario facts, and the relationship grants needed for those candidates in bounded query shapes.

Single-resource ReviewCase detail authorization may keep its existing command-oriented implementation; this constraint applies to the high-frequency Product collection algorithm.

### Scale/query-count regression

A PostgreSQL integration test must prove query growth is not linear in unrelated/hidden Case or Finding count.

Required fixture shape:

```text
Stage A
User U can see 5 Cases
record:
- first page membership
- total
- SQL statement/query count Q5

Stage B
keep the same 5 visible Cases
add unrelated/hidden Cases until organization has about 100 Cases
add Findings and FindingParticipants under those hidden Cases
request the same page again
record Q100
```

Required result:

```text
visible page membership unchanged
visible total unchanged
Q100 does not grow per hidden Case/Finding
```

The test must assert a fixed small constant bound, not merely inspect logs. A reasonable acceptance form is:

```text
Q100 <= Q5 + 2
```

or a stricter equivalent justified by the implementation.

A query count that grows proportionally with hidden Case/Finding count fails the Gate even if response membership is correct.

### Collection presentation proof

Frontend/component/browser tests prove:

- React renders only server-returned authorized `items`;
- page controls use server `total/limit/offset` rather than an unbounded local list;
- each row links to the original Case;
- lifecycle/timing comes from server fields;
- platform role, Workbench membership, cached navigation state, or management scope does not broaden the list;
- no frontend canonical percent-complete field is introduced.

`system_admin` without business relationships gets no frontend business bypass.

## ReviewCase detail authorization ordering

For `/review-cases/:caseId`, ordinary Case GET is the primary authorization gate:

```text
route entered
→ GET /api/v1/review-cases/{caseId}
   ├── success
   │    → generic Case may render
   │    → subordinate reads may proceed
   └── unauthorized/non-disclosing missing
        → safe unavailable state
        → no members/Findings/progress/Activity details from cache
```

Tests include known unauthorized same-org and foreign-org Case IDs and verify no detail leakage beyond established backend behavior.

## Case server-field fidelity

A visible Case fixture proves UI consumption of:

```text
title
lifecycle
scenario_key
scenario_version
planned_start_at
planned_end_at
started_at
fieldwork_completed_at
closed_at
created_at
```

Timestamp formatting is presentation-only. No competing lifecycle/deadline classification is derived.

## Scenario UI registry acceptance

M3.5.2 cannot pass without a centralized executable Scenario UI registry keyed exactly by:

```text
(scenario_key, scenario_version)
```

At minimum:

```text
process_review@1 → ProcessReviewV1 Case adapter
```

The adapter may render existing `area_code` and `review_type` Case scenario fields. Generic Workbench/Case code must not contain distributed `process_review` identity branches.

### Exact-version counterexample

A unit/component test must distinguish at least:

```text
process_review@1 → AdapterV1
process_review@2 → AdapterV2
```

then request `process_review@99`.

Expected:

```text
not AdapterV1
not AdapterV2
not latest / nearest / key-only fallback

generic Case fields remain visible if Case authorization succeeded
Scenario-specific section explicitly unsupported/unavailable
Scenario-specific editing absent/disabled
```

Registry adapters do not own authorization, lifecycle, overdue, management scope, recipient, or provenance truth.

## Findings-on-Case acceptance

The Findings section consumes:

```http
GET /api/v1/review-cases/{case_id}/findings
```

Returned rows retain original Finding identity and server title/severity/lifecycle/raised_at.

M3.5.2 adds no Finding transition, participant mutation, rectification/verification form, Action work, or Finding scenario editing.

No canonical Case progress/closure total is recomputed from this list when M3.3 already owns aggregates.

## Member display identity acceptance

The baseline Case member relationship response has `user_id / role_key / joined_at` but no `display_name`, while general User APIs are system-admin-only.

M3.5.2 may introduce the Gate-approved **Case-scoped display identity enrichment** only after current Case visibility succeeds.

PostgreSQL/API tests must prove:

```text
authorized Case viewer
→ member relationship rows resolve display_name for exactly those member user_ids

unauthorized/foreign Case
→ no member relationship or display identity is disclosed
```

The Product Surface must not call:

```http
GET /api/v1/admin/users
GET /api/v1/admin/users/{user_id}
```

for ordinary Case rendering.

No organization-wide ordinary-user directory may be introduced.

Acceptance also confirms:

- CaseMember remains the authoritative relationship;
- display_name is presentation identity only;
- no member mutation UI is added;
- frontend role checks such as `role_key === "lead" → canManage` are absent.

A source/diff review must reject any client or backend shortcut that converts this enrichment into new authorization semantics.

## Optional management-progress acceptance

M3.3 progress authorization is narrower than ordinary Case visibility.

Acceptance includes two users against a visible Case shape:

```text
User M
→ ordinary Case GET authorized
→ management progress authorized
→ returned server progress summary renders

User V
→ ordinary Case GET authorized
→ management progress non-disclosing 404
→ Case remains visible
→ summary omitted/unavailable
→ no TypeScript fallback recomputation
```

When progress exists, UI displays returned server facts such as deadline_bucket, Finding lifecycle counts, Action lifecycle counts, overdue count and due-soon count.

No `overallProgress` or alternate deadline rule is added.

## ReviewCase Activity read prerequisite acceptance

Implementation may add:

```http
GET /api/v1/review-cases/{case_id}/activities
```

only as the Gate-approved read-only ReviewCase-subject history.

### Authorization proof

PostgreSQL/API tests prove:

```text
authorized Case viewer
→ endpoint returns allowed ReviewCase-subject Activity rows

known unauthorized same-org Case
→ non-disclosing refusal

foreign-org Case UUID
→ non-disclosing refusal
```

Activity existence never grants access.

### Subject-isolation proof

Create one Case with mixed Activity facts:

```text
ReviewCase-subject Activity A
Finding-subject Activity F
ActionItem-subject Activity X
Submission-subject Activity S
```

The Case Activity endpoint returns only `A`.

It must not leak child event type, child IDs, actor, metadata, or child count through this endpoint.

This counterexample is required even if `process_review@1` currently lets a lead view all Findings, because future Scenario versions may differ.

### Metadata exclusion proof

The first M3.5.2 Activity wire DTO is exactly presentation-safe and metadata-free:

```text
id
subject_type
subject_id
event_type
actor_id
occurred_at
```

Tests/OpenAPI review must confirm `metadata` is not emitted by this endpoint.

A later Product need for Activity metadata requires explicit field-by-field review rather than generic JSON exposure.

### Append-only/no-side-effect proof

Before/after Activity GET verify:

```text
Activity count unchanged
ReviewCase lifecycle unchanged
Notification state unchanged
no durable product/timeline row created
```

No migration or new Activity persistence table is permitted.

### Ordering proof

Multiple Case-subject Activities with equal/different `occurred_at` values must return in the documented deterministic order using `occurred_at` plus stable Activity ID tie-breaker.

## Case mutation exclusion acceptance

Source/diff review confirms M3.5.2 Product Surface adds no controls for:

```text
create Case
transition Case
add/change/remove Case member
```

and no frontend workflow/permission matrix to decide such controls.

Existing backend command endpoints remain unchanged; their absence from this Product slice is intentional.

## Shared API client acceptance

All M3.5.2 business requests pass through the existing shared API boundary. Feature code must not scatter raw `fetch()` calls.

Tests/source review confirm:

- `/api/v1/*` remains relative/same-origin;
- central 401 still moves Session to anonymous;
- normal 404 is not Session expiry;
- wire DTOs mirror backend transport rather than form a second domain model;
- no auth/session token enters browser storage.

## Loading / error / optional-section independence

Component/browser tests cover:

```text
Workbench loading
Workbench empty
Workbench request failure
ReviewCase collection loading
ReviewCase collection empty
ReviewCase collection request failure
Case loading
Case unavailable/not-found
Scenario unsupported exact version
management progress unavailable while Case remains visible
```

A subordinate/optional request failure must surface safely without displaying stale data from another Case/user or fabricating fallback truth.

## Logout/session-expiry/user-boundary regression

M3.5.2 business data must participate in the M3.5.1 protected-state boundary:

```text
User A loads Workbench / ReviewCase collection / Case A
→ logout or Session 401
→ protected Workbench/collection/Case data disappears
→ User B logs in in same browser context
→ no A collection membership, Case title, relationships, display names, progress, Activity, or Scenario data appears
```

If a query cache is introduced, this must prove protected entries clear/become inaccessible across users.

## Real browser Acceptance

Final M3.5.2 evidence runs through:

```text
fresh PostgreSQL
→ Alembic
→ real FastAPI/Uvicorn
→ HTTPS Vite same-origin proxy
→ real Chromium
```

Mocked component tests cannot replace this proof.

The real-browser fixture should exercise at least:

```text
1. authenticated Workbench populated from M3.1 projection
2. bounded ReviewCase collection page from server Product query
3. collection pagination does not expose hidden candidates
4. Workbench Case link → real current Case authorization
5. visible Case generic fields + exact Scenario section
6. human-readable Case members + visible Findings
7. manager progress success
8. visible non-manager progress 404 while Case remains visible
9. metadata-free Case-subject Activity read
10. stale Workbench link after relationship loss → current authorization refusal
11. hard reload re-fetches current Workbench/collection/Case server truth
12. logout/session boundary removes protected M3.5.2 data
```

The 5-visible-versus-about-100-total SQL query-count regression may remain a PostgreSQL integration test rather than a browser timing test; the browser proof does not replace it.

## Responsive/accessibility regression

M3.5.5 owns final responsive Product proof, but M3.5.2 must have at least one desktop and one narrow-browser check for Workbench and Case viewing.

Verify primary Workbench sections, paged ReviewCase collection controls, Case header, Findings/members/Activity sections, and original-resource links remain reachable; status meaning uses text beyond color; loading/empty/error text remains readable and keyboard navigation works for primary links.

No design-system expansion is required.

## CI acceptance

The implementation candidate keeps all normal pipeline checks green:

```text
backend:
Ruff
mypy
architecture
OpenAPI
Alembic
PostgreSQL pytest
including Product collection hidden-candidate + query-count regressions

frontend:
npm ci from lockfile
typecheck
Oxlint
unit/component tests
production build
browser foundation

real browser:
PostgreSQL + FastAPI + HTTPS Vite + Chromium M3.5.2 journey
```

The bounded ReviewCase Product collection contract, member identity enrichment, and Activity read-contract additions must be included in the existing OpenAPI contract check.

## Implementation diff boundary

After Gate PASS, expected executable diff may include only what is necessary for:

```text
narrow downstream ReviewCase Product collection query service / schema / API adaptation
PostgreSQL query-shape and authorization-safe pagination tests
web/src/api wire contracts / feature APIs
web/src/features/workbench/** or equivalent
web/src/features/review-cases/** or equivalent
web/src/scenarios/** or equivalent exact registry
ProductShell route replacement for M3.5.2
frontend tests/browser fixtures
narrow Case member display-identity read enrichment + tests
narrow read-only Case Activity query/API + tests
composition/main registration only if needed for those read APIs
CI only if Acceptance harness needs a bounded addition
```

The collection prerequisite may read existing Review Core persistence facts directly as a downstream query projection. It must not require changing Review Core mutation/lifecycle semantics or adding a new persistence truth.

Unexpected scope requiring separate review:

```text
migration
new ReviewCase/Product collection persistence entity
Review Core lifecycle/Scenario authorization changes
Notification/Reminder code
M3.3 semantics changes
organization-wide ordinary-user directory
Finding/Action mutation Product UI
new business entities
new frontend auth model
```

## Final Gate checklist

M3.5.2 cannot pass Final Review unless all are true:

```text
Workbench comes directly from M3.1                         ✅
no frontend work-membership reconstruction                 ✅
Workbench links re-enter current resource auth              ✅
ReviewCase collection is bounded/paginated server-side      ✅
collection authorization precedes pagination                ✅
hidden candidates do not alter page membership/total        ✅
collection query count does not scale per hidden Case       ✅
no org-wide per-Case command traversal for collection       ✅
exact historical ScenarioPolicy remains collection authority ✅
ReviewCase generic truth comes from server                  ✅
Scenario adapter lookup exact by key + version              ✅
unknown Scenario UI version fails closed                    ✅
Finding rows remain original read resources                 ✅
Case member names are Case-scoped server enrichment          ✅
no ordinary-user org directory/admin API shortcut           ✅
management progress remains optional/narrow-authorized       ✅
no client overdue/progress fallback                         ✅
Case Activity API is read-only + Case-subject-only           ✅
Activity DTO excludes generic metadata JSON                  ✅
no hidden child Activity leakage                            ✅
no Case mutation UI/role matrix in this slice               ✅
shared same-origin API/session contract preserved            ✅
protected business data clears across Session/user           ✅
real PostgreSQL/FastAPI browser Acceptance                   ✅
fixed-base / fixed-head-tree CI green                        ✅
```

M3.5.3 remains locked until M3.5.2 passes Final Review and is merged.
