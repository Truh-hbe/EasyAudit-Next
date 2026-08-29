# M4.1 — Second Scenario Selection & Extension Contract Acceptance Gate

Baseline:

```text
main@c54600d52e0ace0fa60eb982261ca69dceb416b7
```

This Acceptance belongs to `m4-1-second-scenario-selection-contract.md`.

M4.1 is **docs-only**. Passing this Gate approves the second-Scenario architecture direction plus the explicitly documented narrow prerequisites. It does not permit hidden scope expansion beyond those boundaries.

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

`roadmap.md` must record the real merged history:

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

The Product/platform may remain generic; the Scenario itself stays concrete.

## E. Material architecture difference

Acceptance rejects a second Scenario that differs only by labels, colors, field captions or seed data.

Mandatory policy difference:

```text
finding_type = observation
OPEN --accept_observation--> CLOSED
```

without creating an ActionItem or rectification Submission merely to imitate Process Review.

The same Scenario also supports a `nonconformity` path through the existing rectification entities/workflow family.

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

These remain in `ReviewCase.scenario_data` / `Finding.scenario_data`. Acceptance fails if they are promoted to generic columns solely for `compliance_review@1`.

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

Mandatory dual-Scenario proof:

```text
compliance_review@1 + observation + accept_observation
→ allowed when exact compliance policy/authorization allows
→ CLOSED

process_review@1 + OPEN + accept_observation
→ rejected as unknown/invalid action
```

This proves command semantics are Scenario-owned rather than Review Core behavior.

## I. Approved generic backend prerequisite

M4.1 explicitly approves one narrow generic backend prerequisite discovered by source review:

> The generic `/findings/{id}/transitions` path must consume an exact Scenario-owned **direct Finding transition decision** instead of hard-coding Process Review-era permission and target assumptions.

The exact Python class/protocol name is not frozen. The ownership boundary is.

Required conceptual flow:

```text
current persisted Finding + ReviewCase
        ↓
build Scenario-neutral current facts
        ↓
exact Scenario direct-transition decision
        ↓
required_permission
target_lifecycle
        ↓
generic authorization using returned permission
        ↓
generic CAS persistence
        ↓
generic finding.transitioned Activity
```

A decision-object design analogous to existing `CaseCreationDecision` / `SubmissionDecision` is acceptable.

Acceptance fails if the prerequisite is implemented as:

```text
ComplianceFindingLifecycleService
compliance-specific HTTP endpoint
if scenario == compliance_review in generic service
```

## J. Direct-transition decision input facts

The Scenario decision must receive current persisted facts sufficient to validate the direct command, including at minimum:

```text
ReviewCase lifecycle
Finding lifecycle
Finding scenario_data
Finding participant role facts
non-cancelled Action count
whether all non-cancelled Actions are done
reason, when supplied
```

The generic service may pass `scenario_data` as an immutable/read-only mapping. It must not interpret Scenario-specific keys.

Forbidden generic behavior:

```python
if finding.scenario_data["finding_type"] == "observation":
    ...
```

Required ownership:

```text
generic service passes current scenario_data
→ exact compliance policy interprets finding_type
```

Mandatory tests must prove that changing only persisted `finding_type` changes compliance policy behavior without adding a generic branch.

## K. Direct-transition decision output and authorization

The exact Scenario decision must own at least:

```text
required_permission
target_lifecycle
```

The generic service must authorize using the **returned permission** through the exact Scenario authorization policy.

Acceptance fails if generic code continues to assume:

```text
required permission = issue_finding
```

for every direct Finding transition.

The generic service must also remove any Process Review target allowlist equivalent to:

```text
RECTIFYING or VOIDED only
```

The returned target lifecycle is authoritative subject to generic validation/CAS persistence and existing concurrency contracts.

## L. Process Review prerequisite regression proof

The generic prerequisite must preserve the first Scenario exactly.

Mandatory same-surface tests:

```text
process_review@1
OPEN + issue → RECTIFYING
OPEN + void(reason) → VOIDED
OPEN + accept_observation → rejected
```

Existing Process Review participant requirements, Action completion rules, rectification Submission validation, verification behavior and recipient policies remain unchanged.

M4 must not weaken Process Review into a common denominator merely to support the second Scenario.

## M. Activity provenance remains generic

`accept_observation` must use the existing generic Finding transition activity contract:

```text
event_type = finding.transitioned
metadata:
  action = accept_observation
  from_lifecycle = open
  to_lifecycle = closed
  optional reason
```

No `ComplianceActivity`, compliance-specific event table or inferred activity provenance is pre-approved.

The transition and Activity must preserve existing transactional semantics.

## N. Case-closure / direct-close concurrency acceptance

M4.1 pre-approves **no new lock model**.

Executable acceptance must prove on real PostgreSQL that the existing Case closure coordination remains safe when an observation may transition directly `OPEN → CLOSED`.

Hard invariant:

```text
never commit:
ReviewCase = CLOSED
+
any child Finding = non-terminal
```

Required race test includes concurrent:

```text
Case close attempt
vs
accept_observation attempt
```

Safe outcomes include:

```text
Case close observes OPEN and refuses; observation later closes
```

or:

```text
observation commits CLOSED first; Case close then succeeds
```

The test must assert committed database state, not only returned exceptions.

If the real PostgreSQL race demonstrates the existing serialization is insufficient, implementation must stop for Architecture review. It must not silently add a new lock ordering or parent Case lock.

## O. Nonconformity responsibility counterexample

For `compliance_review@1` nonconformity, issuing into rectification requires current responsibility sufficient for remediation.

Minimum expected relationship facts:

```text
responsible_department
owner
```

Missing required relationships must reject issuance through exact Scenario validation.

The observation path must separately prove it does not require a fake owner, ActionItem or rectification Submission solely because Process Review does.

## P. Authenticated-identity-only acceptance

All ordinary M4 participants are existing EasyAudit Users/Departments.

Acceptance rejects runtime identity mechanisms equivalent to:

```text
anonymous token assignee
magic-link owner
guest reviewer
external email actor
phone-number actor
unauthenticated remediation principal
```

Authentication and business role remain separate; authorization derives from authenticated identity plus persisted business relationships.

## Q. Cross-Organization rejection

M4 executable acceptance must include PostgreSQL-backed counterexamples proving a User or Department from Organization B cannot be attached to Organization A's compliance Case/Finding/Action.

Existing organization invariants remain authoritative; no compliance-specific bypass is allowed.

## R. Scenario role specifications remain code-owned policy

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

Role-string reuse does not create a global permission mapping. The same role key may produce different permission outcomes under different exact Scenario policies.

No global `if role == ...` authorization table may be added to generic backend code or React.

## S. Scenario policy module boundary

Executable implementation should primarily add a bounded module equivalent to:

```text
src/easyaudit_next/scenarios/compliance_review/**
```

plus narrow composition registration and the approved generic prerequisite seam.

Static/source review fails if compliance-specific business branches appear in:

```text
review_core generic domain/application services
Workbench generic query service
Management generic query service
Notification generic service
collaboration generic orchestration
HTTP route adapters
```

except ordinary imports/registration at composition boundaries.

## T. Composition-root registration acceptance

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

## U. Generic API reuse acceptance

The compliance Scenario must use existing endpoint families for ReviewCase, Finding, ActionItem, Submission, Activity, Workbench, Management, Notification and nudge behavior.

M4.1 pre-approves zero endpoint families named for the second Scenario.

Acceptance fails on additions equivalent to:

```text
/api/v1/compliance-reviews/*
/api/v1/compliance-findings/*
/api/v1/compliance-actions/*
```

The approved direct-transition prerequisite changes generic behavior behind the existing Finding transition endpoint; it does not create a new endpoint family.

A missing generic capability beyond the approved prerequisite must stop for separate Architecture review.

## V. No duplicated application service stack

Acceptance fails if implementation creates equivalents such as:

```text
ComplianceReviewPlanningService
ComplianceFindingLifecycleService
ComplianceRectificationService
ComplianceWorkbenchQueryService
ComplianceManagementQueryService
```

whose purpose is to copy generic orchestration for one Scenario.

Scenario policy classes are expected; copied generic service stacks are not.

## W. Existing generic entities only

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

No second-Scenario copy of these entities is pre-approved.

## X. Workbench reuse acceptance

A compliance Case/Finding/Action must appear through the existing M3.1 Workbench projection according to exact compliance policy and persisted relationships.

Mandatory counterexample:

```text
same persisted compliance resource
User A has qualifying relationship → appears
User B lacks qualifying relationship → absent
```

No frontend filtering may substitute for server authorization. No `ComplianceWorkbench` is allowed.

## Y. Management reuse acceptance

M3.3 Management remains the authorized server-owned read side.

Compliance resources must appear through existing management query APIs when authorized.

No client-computed compliance KPI, hidden-child aggregate, `ComplianceManagementTask`, `SupervisionRecord` or write-side management workflow is introduced.

## Z. Notification reuse acceptance

Existing Notification subject types remain sufficient:

```text
review_case
finding
action_item
```

Acceptance rejects a schema change solely to add `compliance_finding` or equivalent subject types.

Historical Notification remains delivery history, never current authorization.

## AA. Reminder / nudge reuse acceptance

If compliance Finding/Action nudge is supported, recipient resolution must come from the exact compliance Scenario recipient policy through the existing M3.4 capability.

React request bodies remain recipient-free.

Mandatory network assertion:

```text
recipient IDs absent
```

No new ReviewCase nudge, scheduler, cadence, snooze, escalation or quiet-hours capability is pre-approved.

## AB. Existing Product routes remain shared

Second Scenario Product behavior stays on generic routes:

```text
/review-cases/:caseId
/findings/:findingId
/action-items/:actionItemId
/me/workbench
/me/notifications
/management
```

Acceptance fails if a parallel compliance application is created only to avoid exercising the Scenario UI seam.

## AC. Current frontend seam is recognized as Process Review-shaped

M4 Gate explicitly acknowledges that the current adapter contract contains Process Review-shaped members equivalent to:

```text
RectificationPlanFields
CompletionFields
VerificationRejectFields
approve/reject payload builder
```

and current generic Finding UI contains fixed Process Review command strings.

M4 implementation must not hide this by adding a second hard-coded branch.

## AD. Centralized Scenario interaction extension acceptance

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

## AE. UI adapter remains presentation, not authority

A Scenario interaction adapter may own:

```text
field labels
forms
payload construction
Scenario action strings
presentation hints from returned lifecycle/scenario_data
```

It must not own canonical logic equivalent to:

```text
canExecute = role expression
isAuthorized = relationship expression
transitionIsLegal = client workflow engine
recipientIds = client relationship resolver
```

A rendered compliance command is only an affordance. Backend exact Scenario policy independently authorizes and validates it.

## AF. Shared command/error/refetch behavior acceptance

Scenario-specific interaction rendering must reuse shared Product command transport and authoritative result handling.

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

## AG. Exact UI version acceptance

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

## AH. Exact backend version acceptance

Persisted ReviewCase references an exact immutable ScenarioVersion.

Policy resolution must use exact key/version identity corresponding to that persisted version.

Acceptance fails if compliance cases resolve by key-only or “latest compliance policy”. Historical exact-version behavior must remain stable if `compliance_review@2` exists later.

## AI. Catalog persistence acceptance

Executable implementation must prove how persisted Scenario/ScenarioVersion catalog identity is established for `compliance_review@1`.

No schema migration is pre-approved by M4.1.

If catalog bootstrap/data migration is required, implementation review must prove:

```text
data-only Scenario catalog addition
no mutable rewrite of old ScenarioVersion
no second source of Scenario policy truth
```

Code policy identity and persisted catalog identity must match exactly.

## AJ. Process Review full regression acceptance

Every existing normal Process Review backend and Product acceptance test remains green.

Static/source review must find no removal of existing Process Review validation merely because compliance observation uses a shorter path.

## AK. Required dual-Scenario backend tests

At least one test module must exercise both exact policies through the **same generic service surface**.

Mandatory proof shape:

```text
same service class
same method / endpoint
process_review@1 resource → process policy result
compliance_review@1 resource → compliance policy result
```

Tests that instantiate policy classes directly are useful but insufficient by themselves.

The approved direct Finding transition decision must be exercised through the real generic `transition_finding` path, not only as a policy unit test.

## AL. Required real PostgreSQL multi-Scenario acceptance

Final M4 acceptance must use real PostgreSQL persistence containing both ScenarioVersion identities and resources from both Scenarios in one Organization.

It must prove:

```text
both coexist
exact Case scenario identity remains stable
relationships do not leak between Cases
queries do not confuse Scenario versions
direct transition persists with CAS semantics
```

## AM. Required Product acceptance

The real browser acceptance must include at least:

```text
login authenticated compliance auditor/lead
→ Workbench shows compliance Case responsibility
→ open same generic ReviewCase route
→ exact compliance Case fields render
→ open compliance Finding
→ exact compliance Finding fields render
→ exercise observation direct-close interaction
→ server returns CLOSED
→ authoritative refetch shows CLOSED
```

A separate flow must preserve `process_review@1` Product behavior in the same build.

## AN. Observation direct-close counterexample

Fixture:

```text
compliance_review@1
Finding.lifecycle = OPEN
finding_type = observation
no ActionItem
no owner required solely for rectification
```

Authorized exact-policy actor executes:

```text
accept_observation
```

Expected:

```text
exact compliance direct-transition decision accepts
returned required_permission is authorized by exact Scenario policy
returned target_lifecycle = CLOSED
generic service performs CAS persistence
Finding.lifecycle = CLOSED
no synthetic ActionItem created
no rectification Submission inserted
Activity records action/from/to
```

The same command on `process_review@1` fails through the same generic service surface.

## AO. Nonconformity remains formal counterexample

Fixture:

```text
compliance_review@1
finding_type = nonconformity
```

Acceptance must prove the Scenario does not turn every compliance Finding into an observation shortcut.

The nonconformity path requires formal responsibility and uses existing Action/Submission/verification entities before closure according to exact compliance policy.

## AP. No test-only runtime branching

No runtime behavior equivalent to:

```text
if testScenario:
    bypassPolicy()
```

is allowed.

Fixtures may establish deterministic persisted relationships and ScenarioVersion rows but may not substitute for the business command under acceptance.

## AQ. Architecture dependency check

Existing architecture checks must continue to prevent Review Core importing concrete Scenario packages.

If M4 adds a specific static guard against generic modules importing `scenarios.compliance_review`, that guard may be considered during implementation, but M4.1 does not pre-authorize CI/workflow changes.

The dependency remains:

```text
Scenario implementation → Review Core contracts
not
Review Core → Scenario implementation
```

The approved generic direct-transition contract lives in Review Core capability/contracts and remains Scenario-neutral.

## AR. No low-code generalization acceptance

M4 succeeds if two concrete Scenarios fit the architecture.

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

## AS. No anonymous remediation regression

Process Review and Compliance Review both continue to rely on authenticated EasyAudit users for normal collaboration.

M4 must not revive anonymous remediation as a generic platform primitive.

## AT. Final M4 architecture test

A source reviewer should be able to locate second-Scenario differences primarily in:

```text
src/easyaudit_next/scenarios/compliance_review/**
web/src/scenarios/complianceReviewV1* (or equivalent exact adapter module)
composition/registry registration
```

The only expected generic executable change is the narrow Scenario-neutral prerequisite required to remove the proven Process Review assumption from direct Finding transitions, plus any separately reviewed frontend adapter seam generalization already frozen by this Gate.

Compliance semantics must not be distributed through generic domain/application/query/UI modules.

## AU. Gate decision

M4.1 Gate may pass only when reviewers agree that:

1. `compliance_review@1` is concrete and materially different enough to test the architecture;
2. the observation direct-close path is an intentional exact-Scenario difference rather than a new generic lifecycle;
3. the direct Finding transition abstraction gap is closed in the Gate contract by a Scenario-owned decision carrying `required_permission` and `target_lifecycle`;
4. the decision receives persisted `Finding.scenario_data` plus current relationship/Action facts without generic interpretation;
5. Process Review behavior remains an explicit regression counterexample through the same generic service surface;
6. PostgreSQL closure-vs-direct-close race acceptance is mandatory before any new lock model can be considered;
7. authenticated cross-department collaboration remains the identity model;
8. backend generic services/API reuse is mandatory;
9. the existing frontend adapter's Process Review shape is generalized through one centralized exact-version seam rather than branching generic pages; and
10. no low-code, universal workflow, copied service stack or hidden second source of truth is being introduced.

Only after all Gate documentation is aligned, the exact Gate head passes CI, and Architecture + Acceptance review reports `P1=0 / P2=0` may executable M4 implementation begin.
