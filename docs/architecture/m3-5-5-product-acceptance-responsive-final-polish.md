# M3.5.5 — Product Acceptance, Responsive & Final Polish Architecture Gate

Baseline:

```text
main@4334123c90560982281c08e3b3b31e070a9cd798
```

M3.5.5 is the final implementation slice of the already-approved M3.5 Product Surface architecture stage.

The parent M3.5 Gate already freezes the sequence:

```text
M3.5.1  Product shell + authentication + navigation
M3.5.2  Workbench + ReviewCase surface
M3.5.3  Finding / Action collaboration surface
M3.5.4  Notification + Management + Reminder actions
M3.5.5  Product acceptance / responsive / final polish
```

M3.5.1 through M3.5.4 are merged. M3.5.5 therefore does **not** open a new Product capability stage. It closes the existing one.

This first M3.5.5 commit is Gate-only and documentation-only. No executable Product change is allowed until this Gate passes Architecture + Acceptance review.

## Goal

M3.5.5 proves that the already-built Product Surface works as one coherent product rather than as a collection of individually-correct slices.

It has exactly three responsibilities:

```text
1. final cross-slice Product acceptance
2. responsive + accessibility quality closure
3. presentation-only consistency / polish needed to pass that acceptance
```

The final invariant remains the parent M3.5 invariant:

> The Web product may compose and present existing backend capabilities, but it must not become an independent source of authorization, lifecycle, deadline, reminder-recipient, provenance, or task truth.

M3.5.5 succeeds only if that invariant remains true after the full Product is exercised end-to-end.

## Hard scope boundary

M3.5.5 is not permission to revisit backend/product design because the UI is now being exercised more broadly.

No new backend Product capability is pre-approved.

In particular, M3.5.5 does **not** approve changes to:

```text
src/easyaudit_next/** business capability
alembic/**
Notification schema or lifecycle
Workbench membership/projection semantics
Management projection semantics
Review Core lifecycle or authorization
Scenario policy / recipient resolution
manual nudge recipient semantics
Reminder cadence / scheduler / sweep
Finding deadline
ReviewCase nudge
new manager permission
new Product endpoint
OpenAPI business contract
```

If final acceptance discovers a real backend/domain defect, implementation stops and returns to a separate architecture review. It must not be hidden inside a "polish" PR.

## Expected executable scope after Gate PASS

Executable M3.5.5 work should normally remain inside:

```text
web/src/**
web/tests/browser/**
existing frontend test files
```

and may include narrow updates to the existing real-browser fixture seed/control helpers only where necessary to establish deterministic acceptance preconditions.

Expected presentation changes include:

```text
CSS/layout fixes
semantic markup
accessible labels
focus treatment
responsive composition
consistent loading/error/empty/unavailable states
minor copy/spacing/hierarchy cleanup
small reusable presentation components where they reduce duplicated UI behavior
```

Expected test work includes:

```text
cross-slice mocked browser acceptance
real PostgreSQL + FastAPI multi-user Product journey
responsive viewport assertions
keyboard/accessibility smoke acceptance
stale/current-authorization regression coverage
```

M3.5.5 does not pre-approve:

```text
package.json changes
package-lock.json changes
new frontend dependency
workflow / CI changes
new runtime service
new browser storage contract
new client-side state library merely for polish
```

If one of those becomes genuinely necessary, stop and review it separately.

## Product areas under final acceptance

Final acceptance treats these as one product:

```text
Authentication / session resolution
Product shell / primary navigation
Workbench
ReviewCase
Finding
ActionItem
Notification Center
Management collection / progress
Manual Finding / Action nudge
Scenario UI adapter boundary
```

The test is not merely "can each route render?". The test is whether a user can move through these areas while server-owned truth remains coherent.

## Responsive contract

The parent M3.5 Gate requires common desktop/laptop widths and narrow mobile browser widths.

M3.5.5 freezes these mandatory acceptance viewports:

```text
Desktop/Laptop: 1280 × 720
Narrow Mobile:  375 × 812
```

A narrow-width smoke check should also protect the existing minimum supported document width:

```text
320px CSS viewport width
```

The 320px check does not require every dense secondary fact to remain side-by-side. It requires the document and essential controls to remain usable.

### Responsive success definition

At the mandatory viewports:

- no core page may create accidental **document-level** horizontal scrolling;
- an intentionally horizontally-scrollable local control such as the primary navigation strip is allowed if the rest of the page remains stable;
- content cards may stack rather than shrink into unreadable columns;
- long IDs, titles, error messages and timestamps must wrap safely;
- primary actions remain visible/reachable without hover-only behavior;
- forms and selectors remain operable;
- button/link groups may wrap or stack;
- status meaning remains readable without relying on color alone;
- a user can navigate back out of a detail surface without desktop-only placement assumptions.

M3.5.5 does not freeze pixel-perfect screenshots, a design system, a theme engine, or native-mobile interaction patterns.

## Critical responsive journeys

Responsive acceptance must exercise at least:

```text
Workbench → original resource
ReviewCase → Finding
Finding collaboration / mutation controls
Action completion path
Notification All / Unread + target navigation
Management list → progress → original Finding/Action
manual nudge where authorized
```

A narrow viewport is not allowed to satisfy tests by hiding essential controls that exist at desktop width.

## Accessibility baseline

M3.5.5 closes the basic accessibility requirements already frozen by M3.5.

Mandatory properties:

```text
keyboard-reachable primary actions
logical focus order
visible keyboard focus
semantic input labels / accessible names
no keyboard trap
status/error meaning not conveyed by color alone
readable loading/error/empty/unavailable states
buttons remain buttons; navigation remains links where semantically appropriate
```

The Product may retain native browser focus indicators or add explicit `:focus-visible` treatment. It must not globally suppress focus outlines without an equivalent visible replacement.

This is not a WCAG certification program and does not justify importing a large accessibility framework.

## Final multi-user Product journey

M3.5.5 must add a real end-to-end Product acceptance flow against:

```text
real PostgreSQL
real FastAPI
real browser session cookie
real React Product Surface
```

The journey must use multiple credentialed users representing existing business relationships, conceptually:

```text
Lead
Owner / rectification actor
Reviewer / verification actor
```

A deterministic fixture may seed the initial Organization, users, exact ScenarioVersion, ReviewCase, membership and starting Finding relationships. Setup is not the feature under test.

Once the journey begins, business actions being accepted must occur through the actual Product Surface and existing HTTP endpoints, not by directly editing the database to simulate success.

A valid journey should cover this parent-M3.5 sequence as closely as current merged capabilities permit:

```text
Lead logs in
→ Workbench shows led ReviewCase
→ opens ReviewCase
→ opens current Finding / progress context

Owner logs in
→ Workbench shows rectification responsibility
→ opens Finding
→ creates / performs Action work using existing commands
→ completes required Action state
→ submits Finding for verification

Reviewer logs in
→ Workbench shows verification responsibility
→ opens Finding
→ rejects through existing verification command

Owner logs in again
→ sees authoritative reopened/rectifying server state
→ performs required correction
→ submits again

Reviewer logs in again
→ approves
→ Finding closes

Lead logs in
→ ReviewCase / Management projection reflects the closed Finding from server truth
```

The exact fixture may start from a state that avoids testing already-out-of-scope planning UI, but it must not bypass the Product actions that M3.5 claims to make usable.

## Manual nudge / Notification closure

The final Product journey must also connect M3.4 delivery truth to M3.5.4 Product presentation.

Prefer a deterministic eligible overdue Finding/Action target in the same real acceptance fixture or a companion real-browser case:

```text
Lead / authorized sender
→ clicks existing bodyless Finding or Action nudge
→ server resolves recipients
→ response confirms recipient_count

Recipient logs in
→ persistent Notification exists
→ Notification All/Unread query returns server data
→ click uses typed subject navigation
→ original target API performs current authorization
```

The sender's inbox must not be used as proof of delivery.

No recipient picker or recipient identity reconstruction is allowed.

## Fixture integrity boundary

Existing browser fixture helpers may perform direct database setup/control only to establish or perturb external preconditions, for example:

```text
seed deterministic users/resources
make a target overdue before the Product journey starts
simulate another actor revoking a relationship between T0 and T1
```

They must not become test-only substitutes for Product business actions.

Forbidden acceptance shortcuts include:

```text
DB-update Finding to closed instead of clicking approve
DB-insert Notification instead of invoking nudge when nudge is the behavior under test
DB-mark Action complete instead of using Product command
inject fake frontend state to skip authorization
special test-only Product route that bypasses normal APIs
```

The fixture boundary must remain visibly test-only under `web/tests/browser/**` and must not leak into runtime application composition.

## Current authorization remains authoritative

Cross-slice polish must not turn list/history rows into capability tokens.

Final acceptance includes at least one stale-access counterexample:

```text
T0 user legitimately sees Workbench / Notification / Management pointer
T1 relationship changes
T2 user opens original resource
```

Required behavior:

```text
original resource API re-authorizes
→ current refusal/missing state wins
→ stale protected detail is not rendered
```

List/history presentation may remain as historical/projection data where its own server contract permits it. It never grants subject access.

## Stale mutation behavior

M3.5.5 must preserve existing 404/409/422 authority across the composed Product.

At minimum one real or mocked final flow must prove:

```text
render T0
external change T1
user submits stale command T2
→ backend refusal/conflict
→ UI shows authoritative failure
→ affected data refetches or safely invalidates
→ no blind semantic retry
→ no fake local success
```

Polish is not allowed to convert server refusal into optimistic durable state.

## Session / identity isolation

The final surface must preserve M3.5.1 session boundaries while M3.5.2–M3.5.4 data is mounted.

Mandatory invariants:

```text
logout clears protected Product state
login as another user does not reveal previous user's protected rows/details/messages
late request from old route/view/session cannot overwrite current state
401 returns to safe authentication UX
session token remains HttpOnly and unreadable by React
no EasyAudit auth token in localStorage/sessionStorage
```

M3.5.5 may improve UI state cleanup but must not redesign session semantics.

## Cross-slice presentation consistency

Final polish may normalize presentation conventions across the Product, including:

```text
page headings
status text
section/card spacing
command grouping
pagination presentation
loading copy
empty states
error/unavailable surfaces
back-navigation affordances
mobile stacking
```

Consistency changes remain presentation-only.

They must not create generic abstractions that erase domain boundaries. For example, a reusable visual card is acceptable; a generic client-owned `Task` entity combining Finding and ActionItem is not.

## Deadline / status presentation

Responsive/polish changes must preserve server ownership of deadline truth.

Allowed:

```text
render returned ReviewCase deadline_bucket
render returned Action overdue/due-soon counts
format server timestamps consistently
add non-color text labels
```

Forbidden:

```text
Date.now() decides canonical overdue
frontend recomputes management filter membership
invent Finding overdue
invent health/risk score
invent overallProgress percentage
```

The browser clock may format a timestamp for display, but must not replace server projection truth.

## Scenario UI boundary remains frozen

M3.5.5 may improve layout around Scenario-specific sections, but it must not distribute Scenario identity branching into generic features.

Exact adapter rules remain:

```text
(scenario_key, scenario_version) exact lookup
unknown version → fail closed for Scenario-specific interpretation/editing
no latest / nearest / key-only fallback
```

No low-code form designer or schema engine is added in Final polish.

## Notification / Management / Reminder boundaries remain frozen

M3.5.5 must not add UI controls for:

```text
mark unread
archive/delete Notification
Notification inbox total
Management write-side task
ReviewCase nudge
recipient preview/picker/override
scheduler
cadence
next reminder
snooze
quiet hours
escalation
```

If a control cannot be implemented with an already-merged Product API and truth contract, it is outside this slice.

## Testing strategy

M3.5.5 should strengthen acceptance at three levels without replacing one with another:

```text
1. static/unit/component boundary tests
2. mocked Playwright Product behavior/race/error tests
3. real PostgreSQL + FastAPI browser Product journey
```

Mocked tests are appropriate for deterministic edge/race/error cases.

Real browser acceptance is mandatory for proving:

```text
session cookie integration
real authorization
real mutation persistence
real Workbench/Management/Notification projection updates
multi-user flow
```

A screenshot-only or mocked-only Final Acceptance is insufficient.

## Visual testing boundary

M3.5.5 does not require broad pixel-snapshot or screenshot-diff infrastructure.

Layout acceptance should prefer durable behavioral assertions such as:

```text
critical control visible and enabled/disabled as expected
element bounding boxes remain within viewport/document constraints
no document-level horizontal overflow
keyboard focus reaches named action
navigation lands on expected route
server-confirmed state appears after refetch
```

Screenshots may be retained as debugging artifacts but are not the source of Product truth.

## CI / fixed-head evidence

Final candidate head must pass the existing normal CI without weakening it.

Expected evidence includes:

```text
Ruff
mypy
architecture checks
OpenAPI checks
Alembic path
PostgreSQL pytest
frontend typecheck
frontend lint
frontend unit/component tests
frontend production build
mocked Playwright browser acceptance
real PostgreSQL + FastAPI browser acceptance
```

If CI still runs pull-request merge refs, Final Review must again prove that the successful merge-ref tree is exactly the fixed candidate head tree or otherwise obtain equivalent exact-head evidence.

M3.5.5 must not modify workflow/CI merely to manufacture a green Final run without separate review.

## Final M3.5 review

M3.5.5 Final Review is also the **M3.5 Product Surface Final Review**.

It must answer both questions:

```text
Did M3.5.5 responsive/acceptance work pass?
Did M3.5.1–M3.5.5 as a composed Product preserve the parent M3.5 architecture?
```

Final review therefore rechecks the parent invariant checklist, not only files changed in M3.5.5.

## Merge discipline

During implementation and Final Review the PR remains:

```text
Draft
open
unmerged
```

After Final Architecture / Implementation / Product Acceptance PASS:

```text
fix exact head SHA
verify exact-tree CI
verify base / merge-base / behind=0
exit Draft
merge with expected_head_sha
verify merge parents / tree / new main
```

Only then may M3.5 and M3 as a whole be considered complete.
