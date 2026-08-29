# M4.1 — Second Scenario Selection & Extension Contract

Baseline:

```text
main@c54600d52e0ace0fa60eb982261ca69dceb416b7
```

M4.1 begins only after M3.5 Product Surface is merged and frozen.

This slice is an **Architecture / Acceptance Gate only**. No executable M4 code is authorized until this Gate passes.

M4 exists to prove that EasyAudit-Next is a reusable audit platform rather than a `process_review` application whose abstractions have never been exercised by a materially different Scenario.

The reference second Scenario is frozen as:

```text
scenario_key: compliance_review
version:      1
identity:     compliance_review@1
```

The platform is generic; the Scenario is deliberately concrete. M4 does not introduce a catch-all `general_review` Scenario or a universal workflow engine.

## 1. Architecture objective

The target dependency shape remains:

```text
                       Review Core
                           │
                Scenario capability contracts
                    ┌──────┴──────┐
                    ▼             ▼
          process_review@1   compliance_review@1
                    │             │
                    └──────┬──────┘
                           ▼
          generic application / HTTP services
                           │
       ┌───────────────────┼────────────────────┐
       ▼                   ▼                    ▼
   Workbench           Management       Notification/Reminder
       │                   │                    │
       └───────────────────┴──────────┬─────────┘
                                      ▼
                              Product Surface
                                      │
                              Scenario UI registry
                         ┌────────────┴────────────┐
                         ▼                         ▼
                 process_review@1         compliance_review@1
```

Concrete Scenario modules depend on Review Core contracts. Review Core, generic application services, M3 read sides and generic Product pages do not branch on Scenario identity.

## 2. Why compliance_review@1 is materially different

`compliance_review@1` represents a cross-department compliance / special-review Case in which authenticated audit participants record Findings against explicit requirements.

It is close enough to reuse ReviewCase/Finding/Action/Submission, but deliberately different enough to expose Process Review assumptions.

### Case Scenario data

```text
standard_reference: non-blank string
scope_summary:      non-blank string
```

These remain `ReviewCase.scenario_data` and do not become generic columns.

### Finding Scenario data

```text
criterion_reference: non-blank string
finding_type:        "nonconformity" | "observation"
```

These remain `Finding.scenario_data`.

`finding_type` is Scenario classification, not a lifecycle value.

## 3. Required workflow difference

M4 is not satisfied by changing labels or form fields.

The required difference is:

```text
compliance_review@1

finding_type = nonconformity
    OPEN
      ↓ issue
    RECTIFYING
      ↓ existing Action / rectification Submission rules
    VERIFYING
      ↓ approve / reject
    CLOSED / RECTIFYING

finding_type = observation
    OPEN
      ↓ accept_observation
    CLOSED
```

An accepted observation does not require an artificial ActionItem or rectification Submission merely to imitate Process Review.

The same `accept_observation` action remains invalid for `process_review@1`.

This proves that action semantics and lifecycle mapping are owned by the exact Scenario rather than by Review Core.

## 4. Gate review discovery — direct Finding transition abstraction gap

Source review of the current merged baseline found a real second-Scenario prerequisite.

The existing generic `FindingLifecycleService.transition_finding()` does call exact Scenario operation/workflow policies, but then imposes Process Review-era constraints itself:

```text
required permission = issue_finding
current lifecycle   = OPEN
target lifecycle    ∈ {RECTIFYING, VOIDED}
```

Therefore a valid exact Scenario policy returning:

```text
OPEN + accept_observation → CLOSED
```

would still be rejected by the generic service.

This is not a reason to add a compliance-specific service. It is the abstraction defect M4 is intended to expose.

## 5. Approved backend prerequisite — Scenario-owned direct Finding transition decision

M4.1 approves exactly one narrow generic backend prerequisite:

> The generic `/findings/{id}/transitions` application path must consume an exact Scenario-owned direct Finding transition decision rather than hard-coding the Process Review permission and target lifecycle set.

The exact Python class/protocol spelling is intentionally not frozen. The semantic contract is frozen.

Conceptually:

```text
current persisted Finding + ReviewCase
        ↓
build Scenario-neutral transition facts
        ↓
exact Scenario direct-transition decision
        ↓
required_permission
target_lifecycle
        ↓
generic authorization
        ↓
generic CAS persistence
        ↓
generic finding.transitioned Activity
```

A decision-object pattern analogous to existing `CaseCreationDecision` / `SubmissionDecision` is acceptable. An equivalent design is acceptable only if the same ownership boundary is preserved.

## 6. Mandatory decision input facts

The current Finding transition contexts do not expose `Finding.scenario_data`. That is insufficient for a real second Scenario because `compliance_review@1` must distinguish:

```text
finding_type = observation
finding_type = nonconformity
```

at command time.

The exact Scenario decision must therefore receive current persisted Scenario-neutral facts sufficient to validate the action, including at minimum:

```text
ReviewCase lifecycle
Finding lifecycle
Finding scenario_data
Finding participant role facts
non-cancelled Action count
whether all non-cancelled Actions are done
reason, when supplied
```

This does **not** mean generic code interprets `finding_type`. Generic code only passes an immutable/read-only mapping of current `scenario_data` into the Scenario contract.

Forbidden:

```python
if finding.scenario_data["finding_type"] == "observation":
    ...  # in generic application service
```

Required:

```text
generic service passes scenario_data
→ exact compliance policy interprets finding_type
```

## 7. Mandatory decision output

The direct transition decision must own at least:

```text
required_permission
target_lifecycle
```

The generic service then asks the exact Scenario authorization policy about `required_permission`.

It must not continue to assume:

```text
issue_finding
```

for every direct Finding transition.

For example, `compliance_review@1` may require a reviewer-oriented Scenario permission for `accept_observation`; the exact permission key is owned by the compliance policy rather than by generic code.

The generic service must not maintain a target allowlist equivalent to:

```text
RECTIFYING or VOIDED only
```

The target returned by the exact Scenario decision is authoritative subject to generic CAS/concurrency persistence.

## 8. Activity provenance remains generic

M4.1 does not approve a new Activity schema or compliance-specific event table.

The current generic transition Activity is sufficient:

```text
event_type = finding.transitioned
metadata:
  action
  from_lifecycle
  to_lifecycle
  optional reason
```

`accept_observation` must therefore leave a real auditable Activity fact without inventing `ComplianceActivity` or relying on title/body inference.

A later architecture review may choose more typed event names if independently justified; M4.1 does not require it.

## 9. Process Review regression rule

The generic prerequisite must preserve `process_review@1` behavior exactly.

At minimum:

```text
OPEN + issue → RECTIFYING
OPEN + void(reason) → VOIDED
OPEN + accept_observation → rejected
```

Existing Process Review participant requirements, Action completion rules, rectification Submission validation, reviewer verification and recipient policy remain unchanged.

M4 must not weaken Process Review merely to create a common denominator.

## 10. Closure / concurrency boundary

M4.1 does not pre-approve a new lock or transaction architecture.

Existing Case closure uses the established parent Case closure guard and evaluates persisted Finding terminality. Existing formal verification/reopen uses Case→Finding locking.

A direct `OPEN → CLOSED` observation transition must prove with PostgreSQL concurrency tests that the existing closure coordination remains safe.

Required safety invariant:

```text
never commit ReviewCase=CLOSED while any child Finding is non-terminal
```

Required interleaving evidence includes a concurrent Case-close attempt and `accept_observation` attempt.

Safe outcomes may include:

```text
Case close observes OPEN and refuses; observation later closes
```

or:

```text
observation commits CLOSED first; Case close then succeeds
```

M4.1 does not require a new parent Case lock on the direct transition path unless executable tests prove the existing serialization insufficient. If they do, implementation stops for Architecture review rather than silently adding locks.

## 11. Identity and collaboration boundary

All ordinary participants remain authenticated EasyAudit Users and Departments with explicit persisted business relationships.

M4 must not add:

```text
anonymous remediation token
magic-link responsibility actor
guest owner
guest reviewer
email-only assignee
phone-only assignee
external participant string as authorization identity
```

Cross-department collaboration strengthens identity/relationship semantics rather than bypassing them.

Organization boundaries remain hard.

## 12. Scenario role specifications

M4.1 does not create a global role/permission table.

The compliance Scenario may reuse role keys where business meaning overlaps:

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

A shared role key does not imply shared authorization consequences. Exact Scenario policy remains authoritative.

For `nonconformity`, issuing into rectification requires at minimum:

```text
responsible_department
owner
```

For `observation`, `accept_observation` must not require a fake owner or ActionItem solely because Process Review does.

## 13. Existing entities remain the domain model

M4 reuses:

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

M4 must not add copies such as:

```text
ComplianceCase
ComplianceFinding
ComplianceAction
ObservationTask
ComplianceSubmission
```

`ActionItem` remains the rectification action entity for nonconformities.

## 14. No new generic lifecycle values

M4.1 freezes the current generic lifecycle enums.

No values equivalent to the following are pre-approved:

```text
FindingLifecycle.OBSERVATION
FindingLifecycle.ACCEPTED
FindingLifecycle.NONCONFORMITY
ActionItemLifecycle.WAIVED
ReviewCaseLifecycle.COMPLIANCE_REVIEW
```

Scenario differences are expressed through Scenario data, action names, transition decisions, validation and authorization over existing lifecycle states.

## 15. Backend extension seam

The current composition root already injects one `ScenarioRegistry` into Planning, Finding, Rectification, Verification, Workbench, Management, Notification and Reminder/Nudge services.

M4 implementation is expected to add a bounded module equivalent to:

```text
src/easyaudit_next/scenarios/compliance_review/**
```

and a narrow registration:

```python
registry.register(PROCESS_REVIEW_V1)
registry.register(COMPLIANCE_REVIEW_V1)
```

Forbidden:

```python
if case.scenario_key == "compliance_review":
    use_special_compliance_service()
```

The composition root may enumerate installed immutable policies. It must not become a workflow router.

## 16. Generic HTTP API reuse

The second Scenario uses existing endpoint families for:

```text
ReviewCase creation / transition / membership
Finding creation / transition / participants
ActionItem creation / assignment / transition
Submissions / verification
Activity reads
Workbench
Management
Notifications
manual nudge
```

M4.1 pre-approves zero compliance-specific endpoint families.

Forbidden examples:

```text
/api/v1/compliance-reviews/*
/api/v1/compliance-findings/*
/api/v1/compliance-actions/*
```

The approved direct-transition prerequisite changes generic semantics behind the existing Finding transition endpoint; it does not create a second endpoint.

## 17. No copied application service stack

M4 must not create copies such as:

```text
ComplianceReviewPlanningService
ComplianceFindingLifecycleService
ComplianceRectificationService
ComplianceWorkbenchQueryService
ComplianceManagementQueryService
```

Scenario policy classes are expected. Copied generic orchestration is not.

## 18. M3 read-side reuse

### Workbench

M3.1 remains the sole source of personal work membership. Compliance resources appear through the existing Workbench projection according to exact policy and relationships.

### Management

M3.3 remains the authorized read side. No `ComplianceDashboardRepository`, client KPI truth or second management workflow is approved.

### Notification

M3.2 existing subjects remain sufficient:

```text
review_case
finding
action_item
```

No `compliance_finding` Notification subject is needed.

### Reminder / nudge

M3.4 recipient selection remains Scenario-owned. A compliance recipient policy may use the existing recipient capability, while React submits no recipient IDs.

No new ReviewCase nudge, scheduler, cadence, snooze, escalation or quiet-hours behavior is part of M4.1.

## 19. Product routes remain shared

M3.5 routes remain generic:

```text
/review-cases/:caseId
/findings/:findingId
/action-items/:actionItemId
/me/workbench
/me/notifications
/management
```

M4 must not create a parallel compliance frontend merely to avoid exercising the Scenario UI seam.

## 20. Frontend prerequisite discovered by the second Scenario

M3.5 successfully centralized exact Scenario UI lookup, but its first `ScenarioUiAdapter` remains Process Review-shaped. It directly requires concepts equivalent to:

```text
RectificationPlanFields
CompletionFields
VerificationRejectFields
approve/reject verification payload builder
```

The generic Finding page also directly renders Process Review interaction shapes/actions.

That was sufficient for the first Product Surface. It is not sufficient evidence for two materially different Scenarios.

M4 therefore approves one narrow frontend prerequisite:

> Scenario-specific Finding interaction presentation must move behind the centralized exact-version Scenario UI adapter boundary before `compliance_review@1` Product behavior is complete.

## 21. Scenario interaction adapter boundary

The exact TypeScript spelling is not frozen.

Conceptually:

```text
Generic FindingDetailPage
    │
    ├── generic header / lifecycle / participants / Actions / history
    │
    └── exact ScenarioInteractionSection
            ├── process_review@1 interactions
            └── compliance_review@1 interactions
```

The adapter may own presentation concerns such as:

```text
Scenario-specific fields
labels/forms
payload construction
Scenario command action strings
presentation hints from returned lifecycle/scenario_data
```

It does not own:

```text
authorization
workflow legality
recipient resolution
server lifecycle truth
stale-state override
```

Every command still reaches the generic HTTP endpoint and exact backend Scenario policy.

## 22. Shared command ports

Scenario interaction adapters must reuse the shared Product API boundary and shared error/refetch behavior.

Conceptual ports may include:

```text
transitionFinding(action, reason?)
submitRectification(action, payload)
submitVerification(action, payload)
createAction(...)
```

Adapters do not use raw `fetch()` and do not create compliance-specific transport clients.

Existing authoritative handling remains:

```text
401 authentication
403/404 current access
409 stale/concurrency
422 validation
success → authoritative refetch/invalidation
route late-result isolation
session identity isolation
```

## 23. Exact-version behavior

Both backend and frontend remain exact-version only.

```text
process_review@1    → exact policy / UI adapter
compliance_review@1 → exact policy / UI adapter
compliance_review@99 → no fallback
process_review@99    → no fallback
```

Unknown exact UI versions may show generic authorized fields, but Scenario-specific interpretation/interactions fail closed.

No latest/nearest/key-only/cross-Scenario fallback is allowed.

## 24. Catalog / persistence boundary

Code-defined policy identity and persisted Scenario / ScenarioVersion identity must match exactly.

M4.1 pre-approves **no schema migration**.

If implementation requires deterministic catalog bootstrap/data migration for `compliance_review@1`, it may be reviewed only as:

```text
catalog data addition
no schema addition solely for the second Scenario
no rewrite of immutable historical ScenarioVersion
```

The implementation review must explicitly prove the code policy and persisted catalog pair.

## 25. Scope of this Gate

Before Gate PASS, the branch may change only:

```text
docs/architecture/roadmap.md
docs/architecture/m4-1-second-scenario-selection-contract.md
docs/architecture/m4-1-acceptance.md
```

No executable source, migration, OpenAPI, package/lockfile or workflow/CI change is allowed during Gate review.

## 26. Explicit non-goals

M4.1 does not authorize:

```text
universal workflow engine
BPMN engine
low-code Scenario builder
runtime role designer
runtime permission DSL
universal dynamic form engine
new generic lifecycle states
anonymous responsibility links
new Management workflow entities
custom compliance dashboard domain
new Reminder scheduler/cadence
AI-generated compliance decisions
```

## 27. Architecture success condition

M4 succeeds only when two materially different real Scenarios coexist and a reviewer can still say:

```text
Review Core is generic.
Generic application / HTTP services are shared.
Direct Finding transition meaning is decided by the exact Scenario.
Workbench/Management/Notification/Reminder remain shared.
Product routes remain shared.
Scenario differences are concentrated in exact policy + exact UI adapter modules.
```

The second Scenario is an architecture test, not a reason to generalize everything.
