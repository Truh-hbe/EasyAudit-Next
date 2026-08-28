# M3.5.5 — Product Acceptance, Responsive & Final Polish Acceptance Gate

Baseline:

```text
main@4334123c90560982281c08e3b3b31e070a9cd798
```

This Acceptance belongs to `m3-5-5-product-acceptance-responsive-final-polish.md`.

M3.5.5 is the final M3.5 slice. It is complete only when the composed Product Surface passes real multi-user Product acceptance, responsive/accessibility checks, and final parent-architecture re-review without expanding backend/domain scope.

## A. Gate-stage scope proof

Before executable implementation unlock, the PR must contain exactly two changed files:

```text
docs/architecture/m3-5-5-product-acceptance-responsive-final-polish.md
docs/architecture/m3-5-5-acceptance.md
```

Gate-stage acceptance fails if the diff contains:

```text
web/**
src/easyaudit_next/**
alembic/**
tests executable source
package / lockfile
workflow / CI
OpenAPI generated artifacts
```

The Gate PR remains Draft / open / unmerged.

## B. Frozen baseline

Gate and implementation must remain based on:

```text
4334123c90560982281c08e3b3b31e070a9cd798
```

Final compare must show:

```text
merge-base == baseline
behind == 0
```

before merge.

If `main` advances independently, rebase/retarget review is required rather than silently merging a stale Product baseline.

## C. No backend prerequisite acceptance

M3.5.5 has **zero pre-approved backend capability extensions**.

Executable acceptance fails if Product polish introduces any new endpoint, request field, response field, permission, lifecycle, reminder behavior, deadline semantics, persistence schema or migration.

In particular the following remain forbidden:

```text
Notification inbox total
mark unread/archive/delete
ReviewCase nudge
recipient preview/picker/override
new manager role or permission
Finding deadline
new KPI/health/risk score
scheduler/cadence/snooze/quiet-hours/escalation
new Review Core transition
new Workbench membership rule
new Management projection rule
```

A genuine backend defect discovered during Final Acceptance stops the slice for architecture review.

## D. Allowed implementation shape

After Gate PASS, changed executable files should normally be limited to:

```text
web/src/**
web/tests/browser/**
existing frontend unit/component tests
```

Narrow real-browser fixture seed/control changes under `web/tests/browser/**` are allowed only for deterministic setup/external-actor perturbation.

No package/lockfile/workflow change is pre-approved.

## E. Presentation-only change acceptance

Every runtime change must be classifiable as presentation/interaction quality rather than business truth.

Allowed examples:

```text
responsive CSS
layout stacking/wrapping
accessible names/labels
focus treatment
semantic markup
consistent loading/error/empty states
back-navigation affordances
small reusable visual components
copy/spacing/hierarchy polish
```

Forbidden examples:

```text
client Task/WorkItem domain
client authorization policy
client lifecycle state machine
client overdue predicate
client reminder recipient resolver
client Notification provenance inference
client Management write model
```

## F. Mandatory responsive viewports

Acceptance must run the critical Product surface at:

```text
1280 × 720
375 × 812
```

and include a narrow-width smoke check at:

```text
320px viewport width
```

The 320px smoke may be narrower in scope but must prove the Product does not catastrophically break below the primary mobile fixture.

## G. No accidental document overflow

At mandatory responsive routes, acceptance must assert that the Product does not create unintended document-level horizontal scrolling.

Suitable browser assertion:

```text
document.documentElement.scrollWidth <= document.documentElement.clientWidth
```

or equivalent, with a small documented tolerance only if the browser requires it.

An intentionally local horizontal scroller such as the primary navigation strip is allowed.

Tests must cover long/representative content, not only tiny placeholder values.

## H. Responsive critical-route matrix

At minimum these routes/surfaces are covered at narrow width:

```text
/me/workbench
/review-cases/:caseId
/findings/:findingId
/action-items/:actionItemId
/me/notifications
/management
/management/review-cases/:caseId
```

Acceptance must prove the important action/navigation controls are reachable and not hidden by desktop-only composition.

## I. Workbench responsive acceptance

At desktop and narrow mobile widths:

- server-projected categories/items render without horizontal page failure;
- item links remain reachable;
- no client-side regrouping changes Workbench membership;
- long item title/metadata wraps safely;
- opening an item navigates to the original resource.

## J. ReviewCase responsive acceptance

The ReviewCase surface must remain usable when header/facts/sections stack.

Acceptance proves:

- lifecycle/status remains textual, not color-only;
- Findings remain reachable;
- member/activity/current progress presentation does not overflow the document;
- unsupported Scenario UI state remains explicit and does not fall back to another version;
- back/navigation links remain reachable.

## K. Finding responsive acceptance

The Finding page is a mandatory narrow-width action surface.

Acceptance proves the user can reach and operate existing controls needed for the accepted collaboration flow, including as applicable:

```text
participant/collaboration controls
Action creation/navigation
rectification plan/completion controls
submit for verification
approve/reject/reopen/void presentation where current server state supports it
manual nudge
```

The test does not require every command to be simultaneously visible. It requires the current-state essential command to remain reachable.

No CSS breakpoint may replace backend command authority.

## L. ActionItem responsive acceptance

At narrow width:

- assignment/execution/evidence information remains readable;
- Action transition/completion controls remain reachable;
- due time wraps safely;
- no frontend overdue calculation is introduced;
- manual nudge remains bodyless and server-authoritative.

## M. Notification responsive acceptance

At narrow width:

- All / Unread controls remain reachable;
- rows wrap without document overflow;
- read state is textual;
- mark-read remains server-confirmed/refetched;
- typed target navigation remains reachable;
- no inbox total is invented;
- historical Notification never grants current target access.

## N. Management responsive acceptance

At narrow width:

- existing server filters remain operable;
- `as_of`, `total`, deadline bucket and Finding/Action counts remain server values;
- results stack without rebuilding a client KPI dashboard;
- Management progress drill-through remains reachable;
- Finding/Action nudge shortcuts remain original-resource bodyless commands.

## O. Keyboard primary-navigation acceptance

A keyboard-only smoke journey must prove at least:

```text
focus enters primary navigation
focus indicator is visible
user can activate Workbench / ReviewCase / Finding / Action / Notification navigation as applicable
primary form/action controls can be focused and activated
```

Acceptance fails if primary actions require hover or pointer-only interaction.

## P. Visible focus acceptance

The stylesheet must not globally remove focus indication without replacement.

Browser acceptance should check at least representative:

```text
link
button
input/select
```

for visible focus state or retain reliable UA focus presentation.

This requirement is behavioral; pixel-perfect focus color is not frozen.

## Q. Semantic label acceptance

Representative controls must expose meaningful accessible names through semantic labels, text, `aria-label`, or equivalent.

At minimum cover:

```text
login inputs
management filters
Notification All/Unread controls
primary mutation buttons
pagination buttons
```

Placeholder-only naming is insufficient for required form controls.

## R. Status/error/empty semantics acceptance

Final polish must retain or improve explicit textual states for:

```text
loading
empty
error
unavailable/unauthorized-or-missing
success confirmation
```

Color alone must not carry lifecycle/deadline/read/error meaning.

Existing authoritative API error text/status may be summarized safely but must not be rewritten as success.

## S. Real environment acceptance

M3.5.5 Final Product Acceptance must execute against:

```text
PostgreSQL
Alembic-upgraded schema
FastAPI application
React/Vite Product Surface
Chromium/Playwright
real server Session cookie
```

Mock-only evidence is insufficient for Final M3.5 PASS.

## T. Real multi-user fixture acceptance

The real fixture contains deterministic users for distinct existing business relationships, at minimum conceptually:

```text
Lead
Owner / rectification actor
Reviewer / verification actor
```

Credentials are test-only and may be seeded.

The fixture must bind all users/resources to one deterministic Organization and exact ScenarioVersion suitable for current Process Review acceptance.

No runtime production backdoor may be added for fixture control.

## U. Final Product journey — Lead entry

Real browser acceptance starts with Lead authentication and proves:

```text
login through Product UI
→ existing HttpOnly session established
→ Workbench server projection contains the led ReviewCase
→ Lead opens original ReviewCase
→ current Finding/progress context is reachable
```

Acceptance must not inject the Workbench rows into frontend state.

## V. Final Product journey — Owner rectification

Owner logs in through the Product UI and proves:

```text
Workbench shows rectification responsibility
→ opens original Finding
→ creates/performs Action work through existing Product controls
→ completes required Action state through existing command endpoint
→ submits Finding for verification through Product UI
```

Persistence is verified through subsequent server-backed UI/refetch, not local optimistic state alone.

If current workflow requires a rectification plan before completion/submission, the journey must use that existing command rather than bypass it.

## W. Final Product journey — Reviewer rejection

Reviewer logs in and proves:

```text
Workbench shows verification responsibility
→ opens original Finding
→ rejects through existing verification command
→ returned/refetched server lifecycle becomes authoritative
```

No test fixture DB update substitutes for the reject command.

## X. Final Product journey — Owner second cycle

Owner logs in again and proves:

```text
server-projected Finding is back in the appropriate rectification state
→ performs the required correction/Action state using existing Product commands
→ submits again
```

The UI must not reuse stale pre-rejection state.

## Y. Final Product journey — Reviewer approval

Reviewer logs in again and proves:

```text
verification work is visible from server truth
→ approve through existing Product command
→ Finding closes according to existing backend lifecycle
```

The Product must not fabricate closure before server confirmation.

## Z. Final Product journey — Lead projection closure

Lead logs in again and proves:

```text
ReviewCase and/or Management projection reflects the now-closed Finding
```

The assertion must use existing server-owned counts/projections.

Forbidden closure proof:

```text
frontend manually decrementing open count
frontend computing hidden-child aggregates
frontend hard-coding overallProgress
```

## AA. Manual nudge real acceptance

A real browser case must contain an eligible current Finding or Action target for an authorized sender.

Required:

```text
click existing nudge
→ POST original bodyless command
→ server returns activity_id + recipient_count
→ Product displays server-confirmed result
```

Network assertion proves:

```text
request body == null / absent
```

No recipient identifiers are supplied by React.

## AB. Persistent Notification real acceptance

After real nudge delivery, an eligible recipient logs in and proves:

```text
Notification Center server query returns persisted delivery
→ unread/all semantics are correct
→ target link comes from subject.kind + subject.id
→ opening original target re-enters current authorization
```

The sender's inbox is not used as delivery proof.

## AC. Historical Notification is not capability

Mandatory real or mocked counterexample:

```text
T0 historical Notification exists
T1 target access revoked
T2 Notification remains visible where its own contract permits
T3 user opens target
```

Expected:

```text
original resource authorization refusal wins
protected detail does not render
```

No cached Notification title/body may be expanded into protected target detail.

## AD. Stale Workbench/Management pointer is not capability

Equivalent current-resource authorization recheck is required for at least one stale Workbench or Management pointer.

Old list membership/data must not authorize original-resource detail at click time.

## AE. Stale mutation conflict acceptance

At least one final acceptance case proves:

```text
T0 render valid mutation affordance
T1 external actor changes server truth
T2 user submits stale command
```

Expected backend-authoritative result, depending on existing endpoint contract:

```text
404 / 409 / 422
```

Then:

```text
error/refusal is visible
→ affected state refetches/invalidates
→ no fake success
→ no blind semantic retry
```

## AF. Route late-result isolation

Existing route/view race protections must remain effective after polish.

At minimum regression coverage protects:

```text
old Finding nudge result cannot appear on new Finding
old Action mutation result cannot appear on new Action
old Management filter/page result cannot overwrite current query
old Notification All result cannot overwrite Unread
```

If layout refactoring extracts shared components, these guards must not be lost.

## AG. Session identity isolation

Acceptance proves:

```text
User A protected state visible
→ logout
→ login User B
→ no protected A rows/detail/status remains
```

Late A requests must not populate B's Product state.

## AH. Browser storage acceptance

Browser inspection proves:

```text
localStorage
sessionStorage
```

contain no EasyAudit session/JWT/authentication token.

Existing same-origin HttpOnly cookie semantics remain unchanged.

## AI. Same-origin API acceptance

Runtime Product application code continues to issue relative:

```text
/api/v1/*
```

requests.

M3.5.5 fails if final polish introduces credentialed cross-origin browser API configuration or a client-readable auth token.

## AJ. Scenario exact-version acceptance

Final acceptance re-runs the parent Scenario UI invariant:

```text
known exact version → exact adapter
unknown version → no latest/nearest/key-only fallback
```

Generic authorized fields may render; Scenario-specific interpretation/editing fails closed.

Responsive refactoring must not move Scenario branching into generic pages.

## AK. No frontend business-truth reconstruction

Static/source review must find no new canonical logic equivalent to:

```text
canApprove = role/lifecycle expression
isOverdue = Date.now() > due_at
recipients = assignees/owners mapped in React
overallProgress = client aggregate
Notification origin inferred from title/body/activity scan
```

Presentation labels over returned server facts are allowed.

## AL. No distributed raw transport acceptance

New/refactored feature components continue to use the shared API boundary.

Acceptance fails if polish scatters raw `fetch()` calls or creates divergent DTO copies merely to simplify a component.

## AM. Fixture integrity acceptance

Direct DB fixture helpers are permitted only for setup or deliberate external-actor perturbation.

Source review/tests must prove core Product actions under acceptance are not replaced by fixture commands.

The following are specifically forbidden as journey shortcuts:

```text
DB-close Finding instead of approve
DB-create successful Action instead of Product create
DB-complete Action instead of Product command
DB-insert nudge Notification instead of nudge
DB-mark Notification read instead of Product mark-read when read is under test
```

## AN. No test-only runtime branch acceptance

Runtime code must not contain behavior such as:

```text
if (import.meta.env.MODE === 'test') bypassAuthorization()
if (testFixture) skipMutation()
```

or special Product routes/APIs that do not exist in normal runtime.

## AO. No pixel-snapshot dependency acceptance

M3.5.5 may use screenshots for debugging, but Final PASS must rely on behavioral/semantic assertions.

A screenshot-diff alone cannot prove responsive usability, authorization, or business truth.

No visual-regression dependency/package change is required by this Gate.

## AP. Full normal CI acceptance

Final fixed head must pass existing normal CI, including:

```text
Ruff
mypy
architecture check
OpenAPI check
Alembic upgrade path
PostgreSQL pytest
frontend typecheck
frontend lint
frontend unit/component tests
frontend production build
mocked Playwright browser acceptance
real PostgreSQL + FastAPI browser acceptance
```

No failing/skipped required Product acceptance scenario may be hidden behind a conditional that does not run in normal CI.

## AQ. Responsive tests are actually executed

CI logs must explicitly show the new M3.5.5 responsive/final Product tests entered the executed Playwright suite.

Final Review must not infer coverage merely because test files exist in the repository.

## AR. Real multi-user journey is actually executed

CI logs must explicitly show the real PostgreSQL + FastAPI Product journey executed and passed.

If the real-browser job uses a selective Playwright file list, that list must include the M3.5.5 Final Product acceptance test.

## AS. Fixed-head tree evidence

Before Final Review PASS:

1. freeze candidate head SHA;
2. identify CI run associated with that candidate;
3. if GitHub checked out a PR merge ref, inspect its parents and tree;
4. prove the successful CI tree equals the candidate head tree, or obtain a direct equivalent exact-head run.

No tree drift is allowed.

## AT. Final parent-M3.5 invariant re-review

M3.5.5 Final Review must re-confirm all of:

```text
no second WorkItem/task truth
no second lifecycle
no second overdue rule
no distributed frontend Scenario business branching
unknown Scenario UI versions fail closed
same-origin browser/API contract preserved
no client-readable auth/session token
no system_admin business bypass
no Notification-as-capability access
no client-selected nudge recipients
no Action verification lifecycle invented
no Management write-side domain
no Reminder cadence/scheduler scope creep
all mutations use existing backend APIs/policies
historical Notification provenance remains backend-owned
```

Passing M3.5.5-specific responsive tests without this parent re-review is insufficient.

## AU. Final diff review

Final compare against baseline must be inspected file-by-file.

Any changed file outside the approved presentation/test boundary requires explicit justification and architecture review.

Final review should specifically verify absence of:

```text
alembic migration
backend business source
package/lockfile
workflow/CI
OpenAPI contract expansion
new runtime persistence/store
```

unless separately approved after this Gate.

## AV. Final merge discipline

PR remains:

```text
Draft / open / unmerged
```

through executable implementation and Final Review.

Only after:

```text
Architecture Review PASS
Implementation Review PASS
Product Acceptance PASS
Responsive/Accessibility PASS
exact-tree CI PASS
P1 == 0
P2 == 0
```

may the PR exit Draft.

Merge then uses:

```text
expected_head_sha = <final fixed head>
```

After merge verify:

```text
PR closed / merged / non-Draft
merge parent 1 == frozen baseline/current main base
merge parent 2 == final fixed head
merge tree == reviewed final tree
main == merge commit
```

## AW. M3 completion rule

M3.5.5 merge closes the M3.5 Product Surface architecture stage.

M3 itself may be frozen as complete only after the M3.5.5 merge verification succeeds.

No extra "insurance feature" is required after Final Product Acceptance. Any later Product capability belongs to a new milestone/architecture stage rather than being appended to M3.5.5.
