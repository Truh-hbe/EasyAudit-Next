# M4.1 — Second Scenario Selection & Extension Contract Acceptance Gate

Baseline:

```text
main@c54600d52e0ace0fa60eb982261ca69dceb416b7
```

This Acceptance belongs to `m4-1-second-scenario-selection-contract.md`.

M4.1 is **docs-only**. Passing this Gate approves the second-Scenario architecture direction and implementation boundaries; it does not permit hidden scope expansion outside those boundaries.

## A. Gate-stage scope proof

Before executable implementation unlock, the branch diff must contain exactly:

```text
docs/architecture/roadmap.md
docs/architecture/m4-1-second-scenario-selection-contract.md
docs/architecture/m4-1-acceptance.md
```

Gate fails if it contains:

```text
src/**
web/**
alembic/**
tests executable source
OpenAPI generated artifacts
package / lockfile
workflow / CI
```

The PR remains Draft / open / unmerged during Gate review.

## B. Baseline proof

Gate is based exactly on:

```text
c54600d52e0ace0fa60eb982261ca69dceb416b7
```

Compare must show:

```text
merge-base == baseline
behind == 0
```

No stale pre-M3.5 baseline is acceptable.

## C. Roadmap rebaseline acceptance

`roadmap.md` must no longer describe the project as if M0 were current or M3 had not been used for Collaboration & Management.

It must record:

```text
M0   completed bootstrap
M1   completed platform foundation
M2   completed process_review business loop
M3   completed Collaboration & Management
M3.5 completed Product Surface
M4   next: Second Scenario Validation
```

This is a roadmap correction, not a retroactive renaming of merged PRs.

## D. Second Scenario identity

The selected reference second Scenario is exactly:

```text
compliance_review@1
```

M4 implementation must not silently rename it or substitute a generic catch-all Scenario without reopening Architecture review.

The Product/platform may remain described as generic or general-purpose; the Scenario itself stays concrete.

## E. Why this is a real architecture test

Acceptance rejects a second Scenario that differs only by:

```text
labels
colors
field captions
seed data
```

The compliance Scenario must exercise a materially different policy path over the shared model.

Mandatory difference:

```text
finding_type = observation
OPEN --accept_observation--> CLOSED
```

without creating an ActionItem or rectification Submission merely to mimic Process Review.

The same Scenario also supports a `nonconformity` path using the existing rectification entities/workflow family.

## F. Scenario-specific data stays scenario-specific

Required Case data:

```text
standard_reference
scope_summary
```

Required Finding data:

```text
criterion_reference
finding_type
```

Accepted `finding_type` values:

```text
nonconformity
observation
```

Acceptance fails if these are promoted to new generic ReviewCase/Finding columns solely for `compliance_review@1`.

## G. No new generic lifecycle values

M4.1 pre-approves no new generic lifecycle enum value.

Implementation fails if it adds values equivalent to:

```text
observation
accepted
nonconformity
waived
compliance_review
```

into generic ReviewCase/Finding/Action lifecycle enums merely to express Scenario semantics.

`accept_observation` maps existing `FindingLifecycle.OPEN` to existing `FindingLifecycle.CLOSED` through exact Scenario policy.

## H. Process Review comparison counterexample

Acceptance must include direct tests proving the same command does not become global behavior.

At minimum:

```text
compliance_review@1 + observation + accept_observation
→ allowed when compliance policy/authorization allows
→ CLOSED

process_review@1 + OPEN + accept_observation
→ rejected as unknown/invalid action
```

This proves command semantics are Scenario-owned rather than added to Review Core.

## I. Nonconformity responsibility counterexample

For `compliance_review@1` nonconformity, issuing into rectification requires current responsibility sufficient for remediation.

Minimum expected relationship facts:

```text
responsible_department
owner
```

Acceptance must prove missing required relationships reject issuance through exact Scenario validation.

The observation path must separately prove it does not require a fake owner/Action solely because Process Review does.

## J. Authenticated-identity-only acceptance

All ordinary M4 participants are existing EasyAudit users/departments.

Acceptance rejects any new runtime identity mechanism equivalent to:

```text
anonymous token assignee
magic-link owner
guest reviewer
external email actor
phone-number actor
unauthenticated remediation principal
```

Authentication and business role remain separate, but business authorization always derives from authenticated identity plus persisted business relationships.

## K. Cross-Organization rejection

M4 executable acceptance must include PostgreSQL-backed counterexamples proving a User or Department from Organization B cannot be attached to Organization A's compliance Case/Finding/Action.

Existing M1 organization invariants must remain authoritative; no compliance-specific bypass is allowed.

## L. Scenario role specifications remain code-owned policy

The compliance Scenario may reuse role keys such as:

```text
lead
auditor
reviewer
observer
responsible_department
owner
collaborator
primary
```

Acceptance must prove role-string reuse does not create a global permission mapping.

The same role key may produce different permission outcomes under different exact Scenario policies.

No global `if role == ...` authorization table may be added to generic code or React.

## M. Scenario policy module boundary

Executable implementation should primarily add a bounded module equivalent to:

```text
src/easyaudit_next/scenarios/compliance_review/**
```

and a narrow composition registration.

Static/source review fails if compliance-specific business branches appear in:

```text
review_core/application generic services
review_core generic domain services
Workbench generic query service
Management generic query service
Notification generic service
collaboration generic orchestration
HTTP route adapters
```

except ordinary imports/registration at composition boundaries.

## N. Composition-root registration acceptance

Allowed:

```text
registry.register(PROCESS_REVIEW_V1)
registry.register(COMPLIANCE_REVIEW_V1)
```

Forbidden:

```text
if scenario == compliance_review:
    construct_special_service()
```

The composition root may enumerate installed immutable policies. It must not become a workflow router.

## O. Generic API reuse acceptance

The compliance Scenario must use existing endpoint families for ReviewCase, Finding, ActionItem, Submission, Activity, Workbench, Management, Notification and nudge behavior.

M4.1 pre-approves zero endpoint families named for the second Scenario.

Acceptance fails on additions equivalent to:

```text
/api/v1/compliance-reviews/*
/api/v1/compliance-findings/*
/api/v1/compliance-actions/*
```

A missing generic capability discovered during implementation must stop for separate Architecture review.

## P. No duplicated application service stack

Acceptance fails if implementation creates equivalents such as:

```text
ComplianceReviewPlanningService
ComplianceFindingLifecycleService
ComplianceRectificationService
ComplianceWorkbenchQueryService
ComplianceManagementQueryService
```

whose purpose is only to copy generic services for one Scenario.

Scenario policy classes are expected; copied generic orchestration is not.

## Q. Existing generic entities only

M4.1 requires reuse of:

```text
ReviewPlan
ReviewCase
CaseMember
Finding
FindingParticipant
ActionItem
ActionAssignee
Submission
Activity
Notification
```

No second-Scenario entity equivalent to these is pre-approved.

## R. Workbench reuse acceptance

A compliance Case/Finding/Action must appear through the existing M3.1 Workbench projection according to exact compliance policy and relationships.

Mandatory counterexample:

```text
same persisted compliance resource
User A has qualifying relationship → appears
User B lacks qualifying relationship → absent
```

No frontend filtering may substitute for server authorization.

No ComplianceWorkbench is allowed.

## S. Management reuse acceptance

M3.3 Management remains server-owned authorized projection.

Compliance resources must appear through existing management query APIs when authorized.

No client-computed compliance KPI or hidden-child aggregate is allowed.

No `ComplianceManagementTask`, `SupervisionRecord`, or write-side management workflow is introduced.

## T. Notification reuse acceptance

Existing Notification subject types remain sufficient:

```text
review_case
finding
action_item
```

Acceptance rejects a schema change solely to add `compliance_finding` or equivalent subject types.

Historical Notification remains delivery history, never current authorization.

## U. Reminder / nudge reuse acceptance

If compliance Finding/Action nudge is supported, recipient resolution must come from the exact compliance Scenario recipient policy through the existing M3.4 capability.

React request body remains recipient-free.

Mandatory network assertion for manual nudge:

```text
recipient IDs absent
```

No new ReviewCase nudge, scheduler, cadence, snooze, escalation or quiet-hours capability is pre-approved.

## V. Existing Product routes remain shared

Second Scenario Product behavior must remain on generic routes:

```text
/review-cases/:caseId
/findings/:findingId
/action-items/:actionItemId
/me/workbench
/me/notifications
/management
```

Acceptance fails if a parallel compliance application is created only to avoid exercising the Scenario UI seam.

## W. Current frontend seam is recognized as Process Review-shaped

M4 Gate explicitly acknowledges the current adapter contract contains Process Review-shaped members equivalent to:

```text
RectificationPlanFields
CompletionFields
VerificationRejectFields
approve/reject payload builder
```

and current generic Finding UI contains fixed Process Review command strings.

This is the primary frontend extension proof for M4.

M4 implementation must not hide that fact by adding a second hard-coded branch.

## X. Centralized Scenario interaction extension acceptance

Before compliance Product behavior passes, Scenario-specific Finding command/form presentation must be resolved through the centralized exact-version adapter seam.

The exact TypeScript type name is not frozen.

Required structural result:

```text
Generic Finding page
→ generic facts/relationships/history
→ resolve exact Scenario adapter
→ render exact Scenario interaction section
```

Generic Finding code must not contain branches equivalent to:

```ts
if (scenarioKey === 'process_review') ...
if (scenarioKey === 'compliance_review') ...
```

## Y. UI adapter remains presentation, not authority

A Scenario interaction adapter may own:

```text
field labels
forms
payload construction
Scenario action strings
presentation hints from returned lifecycle/data
```

It must not own canonical logic equivalent to:

```text
canExecute = role expression
isAuthorized = relationship expression
transitionIsLegal = client workflow engine
recipientIds = client relationship resolver
```

A rendered compliance command remains only an affordance. Backend exact Scenario policy independently authorizes and validates the command at execution time.

## Z. Shared command/error/refetch behavior acceptance

Scenario-specific interaction rendering must reuse shared Product command transport and standard authoritative result handling.

Acceptance must preserve:

```text
401 auth handling
403/404 current-access handling
409 stale/concurrency handling
422 validation handling
successful mutation → authoritative refetch/invalidation
route late-result isolation
session identity isolation
```

The adapter must not bypass shared transport with raw `fetch()`.

## AA. Exact UI version acceptance

With registry entries such as:

```text
process_review@1
compliance_review@1
```

mandatory counterexamples include:

```text
compliance_review@99
process_review@99
```

Expected:

```text
no latest fallback
no key-only fallback
no cross-Scenario fallback
generic authorized facts may render
Scenario-specific fields/interactions fail closed
```

## AB. Exact backend version acceptance

Persisted ReviewCase references an exact immutable ScenarioVersion.

Policy resolution must use exact key/version identity corresponding to that persisted version.

Acceptance fails if compliance cases are resolved by key-only or “latest compliance policy”.

Historical exact-version behavior must remain stable if a future `compliance_review@2` exists.

## AC. Catalog persistence acceptance

Executable implementation must explicitly prove how persisted Scenario/ScenarioVersion catalog identity is established for `compliance_review@1`.

No schema migration is pre-approved by M4.1.

If a catalog-data migration/bootstrap is required, implementation review must prove:

```text
data-only Scenario catalog addition
no mutable rewrite of old ScenarioVersion
no second source of Scenario policy truth
```

Code policy identity and persisted catalog identity must match exactly.

## AD. Process Review regression acceptance

Every existing normal Process Review backend and Product acceptance test remains green.

M4 must not weaken Process Review in order to simplify a shared abstraction.

Static/source review must find no removal of existing Process Review validation merely because compliance observation uses a shorter path.

## AE. Required dual-Scenario backend tests

At least one test module must exercise both exact policies through the same generic service surface.

Mandatory proof shape:

```text
same service class
same method / endpoint
process_review@1 resource → process policy result
compliance_review@1 resource → compliance policy result
```

Tests that instantiate policy classes directly are useful but insufficient by themselves.

## AF. Required real PostgreSQL multi-Scenario acceptance

Final M4 acceptance must use real PostgreSQL persistence containing both ScenarioVersion identities and resources from both Scenarios in one Organization.

It must prove:

```text
both can coexist
exact Case scenario identity remains stable
relationships do not leak between Cases
queries do not confuse Scenario versions
```

## AG. Required Product acceptance

The real browser acceptance must include at least:

```text
login authenticated compliance auditor/lead
→ Workbench shows compliance Case responsibility
→ open same generic ReviewCase route
→ exact compliance Case fields render
→ open compliance Finding
→ exact compliance Finding fields render
→ exercise the observation direct-close interaction
→ server returns CLOSED
→ authoritative refetch shows CLOSED
```

A separate flow must preserve `process_review@1` Product behavior in the same build.

## AH. Observation direct-close counterexample

This is the most important second-Scenario proof.

Fixture:

```text
compliance_review@1
Finding.lifecycle = OPEN
finding_type = observation
no ActionItem
no owner required solely for rectification
```

Authorized reviewer executes:

```text
accept_observation
```

Expected:

```text
server exact compliance policy accepts
Finding.lifecycle = CLOSED
no synthetic ActionItem created
no rectification Submission inserted
Activity records the real command result
```

The same action on `process_review@1` fails.

## AI. Nonconformity remains formal counterexample

Fixture:

```text
compliance_review@1
finding_type = nonconformity
```

Acceptance must prove the Scenario does not turn every compliance finding into an observation shortcut.

The nonconformity path requires formal responsibility and uses existing Action/Submission/verification entities before closure according to exact compliance policy.

## AJ. No test-only runtime branching

No runtime behavior equivalent to:

```text
if testScenario:
    bypassPolicy()
```

is allowed.

Fixtures may establish deterministic persisted relationships and ScenarioVersion rows but may not substitute for the business command under acceptance.

## AK. Architecture dependency check

Existing architecture checks must continue to prevent Review Core importing concrete Scenario packages.

If M4 adds a specific static guard against generic modules importing `scenarios.compliance_review`, that guard may be considered during implementation, but M4.1 does not pre-authorize CI/workflow changes.

The fundamental dependency remains:

```text
Scenario implementation → Review Core contracts
not
Review Core → Scenario implementation
```

## AL. No low-code generalization acceptance

M4 is successful if two concrete Scenarios fit the architecture.

M4 fails if implementation responds by introducing speculative machinery such as:

```text
workflow DSL
permission DSL
runtime role editor
universal form schema engine
BPMN runtime
dynamic entity definitions
```

unless a separate Architecture Gate proves a concrete need beyond the two real Scenarios.

## AM. No anonymous remediation regression

Process Review and Compliance Review both continue to rely on authenticated EasyAudit users for normal collaboration.

M4 must not revive anonymous remediation as a generic platform primitive.

## AN. Final M4 architecture test

A source reviewer should be able to locate second-Scenario differences primarily in:

```text
src/easyaudit_next/scenarios/compliance_review/**
web/src/scenarios/complianceReviewV1* (or equivalent exact adapter module)
composition/registry registration
```

and **not** find those differences distributed through generic domain/application/query/UI modules.

## AO. Gate decision

M4.1 Gate may pass only when reviewers agree that:

1. `compliance_review@1` is concrete and materially different enough to test the architecture;
2. the observation direct-close path is an intentional Scenario difference rather than a new generic lifecycle;
3. authenticated cross-department collaboration remains the identity model;
4. backend generic services/API reuse is mandatory;
5. the existing frontend adapter's Process Review shape is explicitly generalized through one centralized seam rather than branching generic pages; and
6. no low-code or universal workflow scope is being smuggled into the second-Scenario proof.

Only after that PASS may executable M4 implementation begin.
