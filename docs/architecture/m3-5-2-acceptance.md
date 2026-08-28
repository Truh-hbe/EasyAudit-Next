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

Any `web/**`, backend source, migration, package, lockfile, or CI change is executable implementation and is forbidden before Gate approval.

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
```

## No-second-Workbench acceptance

Executable tests must prove the `/me/workbench` UI is populated from exactly:

```http
GET /api/v1/me/workbench
```

and does not reconstruct personal work by querying broad Case/Finding/Action collections.

A valid fixture must include at least one item in multiple distinct server categories, for example:

```text
case_responsibilities
finding_responsibilities
action_responsibilities
verification_queue
due_soon
overdue
```

The UI membership must match the server response even when role/lifecycle combinations would tempt client inference.

Acceptance fails if frontend code contains business selection equivalent to:

```ts
if (case.role === "lead") work.push(case)
if (finding.lifecycle === "verifying") verification.push(finding)
if (action.dueAt < Date.now()) overdue.push(action)
```

Presentation grouping, labels, empty sections, sorting, and display filtering remain allowed.

## Workbench original-resource navigation

Tests must prove each server-projected item navigates to its original resource identity:

```text
Case → /review-cases/:caseId
Finding → /findings/:findingId
Action → /action-items/:actionItemId
```

No Workbench item gets an independent detail lifecycle or domain route.

Finding/Action destinations may remain explicit M3.5.3 placeholders in this slice.

## Workbench stale-link authorization counterexample

A real backend/browser Acceptance must cover:

```text
T0
User A has current relationship
→ GET /me/workbench includes Case C

T1
server-side relationship is changed/removed by an authorized setup actor

T2
User A follows the old Workbench link to /review-cases/C
→ Product Surface performs normal current Case GET
→ backend refuses/non-discloses current access
→ Case detail is not rendered from stale Workbench data
```

After refusal, the browser must not reveal cached/stale:

```text
Case title
lifecycle
scenario_data
members
Findings
management progress
Activity
```

A stale Workbench pointer is never a capability token.

## ReviewCase collection acceptance

`/review-cases` must consume the existing authorized Case collection endpoint.

Tests must prove:

- only server-returned Cases render;
- each row links to the original Case route;
- generic lifecycle/timing text comes from response fields;
- no management scope or platform role broadens the list; and
- no client-generated percent-complete field is introduced.

`system_admin` without business relationships remains unable to use frontend navigation as a business bypass.

## ReviewCase detail authorization ordering

For `/review-cases/:caseId`, the ordinary Case GET is the primary authorization gate.

Required ordering:

```text
route entered
→ GET /api/v1/review-cases/{caseId}
   ├── success
   │    → generic Case may render
   │    → subordinate reads may proceed
   └── unauthorized/non-disclosing missing
        → safe unavailable state
        → no members/Findings/progress/Activity details shown from cache
```

Tests must include a known unauthorized/foreign Case UUID and verify no resource existence/detail leakage beyond the established backend behavior.

## Case server-field fidelity

A visible Case fixture must prove the UI consumes server fields including:

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

The UI may format timestamps consistently but must not derive a competing lifecycle/deadline classification.

## Scenario UI registry acceptance

M3.5.2 cannot pass without an executable centralized Scenario UI registry.

Tests must prove exact registration and lookup by:

```text
(scenario_key, scenario_version)
```

At minimum:

```text
process_review@1 → ProcessReviewV1 Case adapter
```

The `process_review@1` adapter may render existing Case `scenario_data` fields:

```text
area_code
review_type
```

Generic Case/Workbench code must not contain distributed Process Review identity checks.

### Exact-version counterexample

A unit/component test must register at least two distinguishable adapters, e.g.:

```text
process_review@1 → AdapterV1
process_review@2 → AdapterV2
```

then request:

```text
process_review@99
```

Expected:

```text
not AdapterV1
not AdapterV2
not latest
not nearest
not key-only fallback

→ generic Case fields remain visible if server authorization succeeded
→ Scenario-specific section explicitly says unsupported/unavailable
→ Scenario-specific editing is absent/disabled
```

The registry must not own authorization, lifecycle, overdue, recipient, or provenance logic.

## Findings-on-Case acceptance

The Case Findings section consumes:

```http
GET /api/v1/review-cases/{case_id}/findings
```

Tests must prove returned Finding rows retain original identity and server fields such as title/severity/lifecycle/raised_at.

M3.5.2 must not add:

```text
Finding transition commands
participant mutation
rectification forms
verification forms
Action work
Finding scenario editing
```

No canonical Case progress/closure total may be recomputed from this list when M3.3 owns those aggregates.

## Member read acceptance

The members section consumes:

```http
GET /api/v1/review-cases/{case_id}/members
```

Acceptance must prove:

- returned members render as relationship facts;
- role keys may be displayed but do not create client authorization;
- no add/remove/change member mutation UI is introduced in M3.5.2.

A source review check should reject frontend logic equivalent to:

```ts
member.role_key === "lead" && enableManageButton
```

as business authority.

## Optional management-progress acceptance

The M3.3 progress endpoint has narrower management authorization than ordinary Case visibility.

Acceptance must include two users against the same visible Case shape:

```text
User M
→ ordinary Case GET authorized
→ management progress GET authorized
→ server factual progress summary renders

User V
→ ordinary Case GET authorized
→ management progress GET non-disclosing 404
→ Case remains visible
→ management progress section omitted/unavailable
→ no TypeScript fallback recomputation
```

This is a hard counterexample against coupling `view_case` to `manage_case_members`.

When progress is available, tests should verify the UI displays returned server facts such as:

```text
deadline_bucket
Finding lifecycle counts
Action lifecycle counts
overdue count
due-soon count
```

without inventing `overallProgress` or a second deadline formula.

## ReviewCase Activity read prerequisite acceptance

If implementation adds the Gate-approved endpoint:

```http
GET /api/v1/review-cases/{case_id}/activities
```

it must be read-only and preserve current Case authorization.

### Authorization proof

PostgreSQL/API tests must prove:

```text
authorized Case viewer
→ endpoint returns allowed Case-subject Activity rows

known unauthorized same-org Case
→ non-disclosing refusal

foreign-org Case UUID
→ non-disclosing refusal
```

No Activity data may be returned merely because the Activity row exists.

### Subject-isolation proof

Create one Case with mixed Activity facts:

```text
ReviewCase-subject Activity A
Finding-subject Activity F
ActionItem-subject Activity X
Submission-subject Activity S
```

The M3.5.2 Case Activity endpoint must return only `A`.

It must not leak child event type, child IDs, actor/payload, or even child count through this endpoint.

This counterexample is required even if `process_review@1` currently lets a lead see all Findings, because the contract must remain safe for future Scenario versions.

### Append-only/no-side-effect proof

Before/after the Activity GET, verify no durable state changes:

```text
Activity count unchanged
ReviewCase lifecycle unchanged
Notification state unchanged
Session business state unchanged
```

No migration or new Activity persistence table is permitted.

### DTO fidelity

The browser/API DTO may expose only existing Activity facts required for presentation, such as:

```text
id
subject_type
subject_id
event_type
actor_id
occurred_at
safe existing payload/metadata if included
```

No second event taxonomy, Notification mapping, or inferred business status.

## Case mutation exclusion acceptance

Source/diff review must confirm M3.5.2 adds no Product Surface controls for:

```text
create Case
transition Case
add/change/remove Case member
```

and no frontend lifecycle/permission matrix is added to decide such controls.

Existing backend mutation endpoints remain unchanged; absence of UI commands in this slice is intentional.

## Shared API client acceptance

All M3.5.2 business requests must pass through the existing shared API boundary.

Feature code must not scatter direct raw `fetch()` calls.

Tests/source review must confirm:

- `/api/v1/*` remains relative/same-origin;
- central 401 still transitions Session to anonymous;
- normal 404 does not become Session expiry;
- wire DTOs mirror backend shape rather than create a second domain model;
- no auth/session token enters browser storage.

## Loading / error / optional-section independence

Component/browser tests must cover:

```text
Workbench loading
Workbench empty
Workbench request failure
Case loading
Case unavailable/not-found
Scenario unsupported exact version
management progress unavailable while Case remains visible
```

A failure in optional management progress must not erase an authorized Case or trigger client progress reconstruction.

A subordinate read failure must surface safely without displaying stale data from another Case/user.

## Logout/session-expiry/user-boundary regression

M3.5.1 already established protected-state isolation. M3.5.2 must prove newly introduced business data participates in the same boundary.

At minimum:

```text
User A loads Workbench / Case A
→ logout or Session 401
→ protected Workbench/Case data disappears
→ User B logs in in same browser context
→ no User A Case title, relationships, progress, Activity, or Scenario data appears
```

If a query cache is introduced, this test must prove its protected entries are cleared/inaccessible across the user boundary.

## Real browser Acceptance

Final M3.5.2 evidence must run through the existing real chain:

```text
fresh PostgreSQL
→ Alembic
→ real FastAPI/Uvicorn
→ HTTPS Vite same-origin proxy
→ real Chromium
```

Mocked component tests remain useful but cannot replace this proof.

The real-browser fixture should exercise at least:

```text
1. authenticated Workbench populated from M3.1 projection
2. Workbench Case link → real current Case authorization
3. visible Case generic fields + exact Scenario section
4. members + visible Findings
5. manager-only progress success
6. visible non-manager Case with progress 404 but Case still visible
7. Case-subject Activity read
8. stale Workbench link after relationship loss → current authorization refusal
9. hard reload re-fetches current Workbench/Case server truth
10. logout/session boundary removes protected M3.5.2 data
```

## Responsive/accessibility regression

M3.5.5 owns final responsive product proof, but M3.5.2 implementation must have at least one desktop and one narrow-browser check for Workbench and Case viewing.

At minimum verify:

```text
primary Workbench sections reachable
Case header readable
Findings/members/Activity sections reachable
original-resource links keyboard reachable
status labels use text, not color only
loading/empty/error text readable
```

No UI redesign/design-system expansion is required.

## CI acceptance

The implementation candidate must keep all existing normal pipeline checks green:

```text
backend:
Ruff
mypy
architecture
OpenAPI
Alembic
PostgreSQL pytest

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

If a new Activity read API is added, OpenAPI must be updated/generated through the existing contract check rather than bypassed.

## Implementation diff boundary

After Gate PASS, expected executable diff may include only what is necessary for:

```text
web/src/api wire contracts / feature APIs
web/src/features/workbench/** or equivalent
web/src/features/review-cases/** or equivalent
web/src/scenarios/** or equivalent exact registry
ProductShell route replacement for M3.5.2
frontend tests/browser fixtures
narrow read-only Case Activity query/API + tests
composition/main registration only if needed for that read API
CI only if Acceptance harness needs a bounded addition
```

Unexpected scope requiring separate review includes:

```text
migration
Review Core lifecycle/Scenario authorization changes
Notification/Reminder code
M3.3 semantics changes
Finding/Action mutation Product UI
new business entities
new frontend auth model
```

## Final Gate checklist

M3.5.2 cannot pass Final Review unless all are true:

```text
Workbench comes directly from M3.1                     ✅
no frontend work-membership reconstruction             ✅
Workbench links re-enter current resource auth          ✅
ReviewCase generic truth comes from server              ✅
Scenario adapter lookup exact by key + version          ✅
unknown Scenario UI version fails closed                ✅
Finding/member sections remain original read resources  ✅
management progress remains optional/narrow-authorized   ✅
no client overdue/progress fallback                     ✅
Case Activity API is read-only + Case-subject-only       ✅
no hidden child Activity leakage                        ✅
no Case mutation UI/role matrix in this slice           ✅
shared same-origin API/session contract preserved        ✅
protected business data clears across Session/user       ✅
real PostgreSQL/FastAPI browser Acceptance               ✅
exact-head / fixed-base-tree CI green                    ✅
```

M3.5.3 remains locked until this slice passes Final Review and is merged.
