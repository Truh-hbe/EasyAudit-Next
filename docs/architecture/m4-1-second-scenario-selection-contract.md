# M4.1 — Second Scenario Selection & Extension Contract

Baseline:

```text
main@c54600d52e0ace0fa60eb982261ca69dceb416b7
```

M4.1 begins only after M3.5 Product Surface is merged and frozen.

This slice is **Architecture / Acceptance Gate only**. It does not authorize executable implementation yet.

The purpose of M4 is to prove that EasyAudit-Next is a reusable audit platform rather than a `process_review` application whose abstractions have never been exercised by a materially different Scenario.

The reference second Scenario selected for that proof is:

```text
scenario_key: compliance_review
version:      1
identity:     compliance_review@1
```

The name describes a concrete compliance / special-review business contract. M4 intentionally does **not** create a catch-all `general_review` Scenario. The platform is generic; a Scenario should remain a bounded business policy.

## 1. Why M4 exists

M2 proved one real Scenario can drive generic Review Core.

M3 proved generic collaboration and management read sides can consume exact Scenario policy.

M3.5 proved one coherent Product Surface can compose those capabilities without owning business truth.

M4 must now prove a second real Scenario can enter the system primarily by adding Scenario-owned policy and UI adapter code rather than by copying the application.

The target dependency shape is:

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

The second Scenario must not reverse any of those arrows.

## 2. Selected reference business shape

`compliance_review@1` represents a cross-department compliance / special-review Case in which multiple authenticated audit participants can record findings against explicit criteria.

It is intentionally close enough to reuse the existing domain model, but different enough to expose Process Review assumptions.

### Case Scenario data

The initial contract requires these exact Scenario-specific Case fields:

```text
standard_reference: non-blank string
scope_summary:      non-blank string
```

Examples of semantic meaning:

```text
standard_reference = governing standard / checklist / requirement set
scope_summary      = bounded scope of this compliance review
```

These remain `scenario_data`; they do not become new generic ReviewCase columns.

### Finding Scenario data

The initial contract requires:

```text
criterion_reference: non-blank string
finding_type:        "nonconformity" | "observation"
```

`criterion_reference` identifies the requirement or criterion against which the finding was recorded.

`finding_type` is Scenario-owned classification. It does not add a generic Finding lifecycle state.

## 3. Material difference from process_review@1

M4 is not satisfied by changing labels or field names.

The second Scenario must exercise at least one genuinely different workflow path.

The frozen difference is:

```text
compliance_review Finding

finding_type = nonconformity
    OPEN
      ↓ issue
    RECTIFYING
      ↓ existing Action / rectification submission rules
    VERIFYING
      ↓ approve / reject
    CLOSED / RECTIFYING

finding_type = observation
    OPEN
      ↓ accept_observation
    CLOSED
```

An accepted observation does **not** require creation of an ActionItem or a rectification Submission merely to imitate Process Review.

This difference proves that Scenario policy can map a new command to existing generic lifecycle states without adding a new generic entity or lifecycle value.

### Explicitly forbidden shortcut

Do not represent the second path as:

```text
if scenario_key == "compliance_review":
    ...
```

inside Review Core, generic application services, HTTP adapters, Workbench, Management, Notification, Reminder or generic React feature pages.

The difference belongs to the exact Scenario policy / UI adapter.

## 4. Identity and collaboration boundary

All real participants remain first-class authenticated EasyAudit users and departments.

M4 freezes:

```text
User / Department identity
+ explicit CaseMember / FindingParticipant / ActionAssignee relationships
```

as the only ordinary collaboration identity model.

M4 must not introduce:

```text
anonymous remediation token
magic-link responsibility actor
guest owner
email-only assignee
phone-only assignee
external participant string as authorization identity
```

This is deliberate. Cross-department collaboration should strengthen identity and relationship semantics rather than bypass them.

Organization boundaries remain hard. A User or Department from another Organization cannot be attached to a Case/Finding/Action in the current Organization.

## 5. Case roles

M4.1 does not create a new generic role table or platform permission taxonomy.

The second Scenario may define code-owned immutable `RoleSpecification` values through the existing Scenario contract.

The initial compliance Scenario reuses these Case role concepts:

```text
lead
 auditor
reviewer
observer
```

Role *keys* may overlap with Process Review where the business meaning genuinely overlaps. Their authorization consequences remain Scenario-owned and are not inferred globally from the string itself.

The architecture proof is not “every Scenario must invent different role names.” The proof is that a shared role key does not become global policy.

## 6. Finding relationship roles

The initial compliance Scenario may reuse:

```text
responsible_department  → Department relationship
owner                   → direct User relationship
collaborator            → direct User relationship
```

with Scenario-specific operation requirements.

For `nonconformity`, issuing the Finding requires current responsibility sufficient for rectification. The expected minimum is:

```text
responsible_department
+ owner
```

For `observation`, `accept_observation` must not require an artificial owner or ActionItem solely to satisfy Process Review assumptions.

This difference is a required M4 counterexample.

## 7. Action and rectification boundary

`ActionItem` remains the generic rectification action entity.

For `nonconformity`, M4 should reuse the existing generic ActionItem model and generic rectification services.

M4 must not create:

```text
ComplianceAction
ObservationTask
SpecialReviewAction
ComplianceFindingSubmission
```

merely because a second Scenario exists.

The exact Scenario policy may define different validation and authorization rules over the same entities.

For `observation`, ActionItem creation is not part of the accepted direct-close path.

## 8. Submission boundary

Submission remains the formal immutable business payload mechanism.

A second Scenario may define Scenario-owned payload validation and action semantics through the existing `SubmissionPolicy` capability.

The architecture goal is:

```text
same Submission entity
same generic service / endpoint family
+ different exact Scenario policy
```

not a copied compliance-specific submission stack.

The observation direct-close path may use the existing Finding transition command and does not require a fake Submission when no formal submission fact is needed.

## 9. No new generic lifecycle values

M4.1 freezes the current generic lifecycle enums.

No new generic values such as:

```text
FindingLifecycle.OBSERVED
FindingLifecycle.ACCEPTED
FindingLifecycle.NONCONFORMITY
ActionItemLifecycle.WAIVED
ReviewCaseLifecycle.COMPLIANCE_REVIEW
```

are pre-approved.

Scenario differences must first be expressed by:

```text
Scenario data
+ Scenario action names
+ Scenario workflow mapping
+ Scenario validation / authorization
```

over existing generic lifecycle states.

A future truly irreducible lifecycle requirement would require a separate Review Core architecture review.

## 10. Backend extension seam

The current composition root already wires all major generic services through one `ScenarioRegistry`.

M4 implementation is expected to add a new bounded module such as:

```text
src/easyaudit_next/scenarios/compliance_review/
```

and register its immutable policy in the composition root.

Allowed conceptual change:

```python
registry.register(PROCESS_REVIEW_V1)
registry.register(COMPLIANCE_REVIEW_V1)
```

Forbidden conceptual change:

```python
if case.scenario_key == "compliance_review":
    use_special_compliance_service()
```

The composition root may know which code-defined Scenario policies are installed. Generic services must not branch on Scenario identity.

## 11. HTTP API reuse boundary

M4 is specifically intended to prove API reuse.

The second Scenario should use the existing generic endpoint families for:

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

M4.1 pre-approves **zero compliance-specific HTTP endpoint families**.

Forbidden examples:

```text
/api/v1/compliance-reviews/*
/api/v1/compliance-findings/*
/api/v1/compliance-actions/*
```

A genuine missing generic capability discovered during implementation stops for architecture review rather than being hidden behind a copied endpoint.

## 12. M3 read-side reuse

The second Scenario must exercise the already merged M3 capabilities rather than bypassing them.

### Workbench

M3.1 continues to own personal work membership.

A compliance Case/Finding/Action must appear through existing Workbench projection semantics when the exact compliance policy grants the relevant relationship/permission.

No second Workbench query service is allowed.

### Management

M3.3 continues to own authorized management projection and deadline aggregates.

No `ComplianceDashboardRepository` or client-side compliance KPI truth is pre-approved.

### Notification

M3.2 continues to own persistent delivery history.

The second Scenario must not add Notification schema variants merely to identify compliance subjects; existing typed ReviewCase/Finding/Action subjects remain sufficient.

### Reminder / nudge

M3.4 recipient selection remains Scenario-owned.

`compliance_review@1` may define its own recipient policy through the existing recipient capability, but React must never select recipient IDs.

No new cadence/scheduler/snooze/escalation infrastructure is part of M4.1.

## 13. Product Surface reuse

M3.5 generic routes remain the product routes:

```text
/review-cases/:caseId
/findings/:findingId
/action-items/:actionItemId
/me/workbench
/me/notifications
/management
```

M4 must not create a parallel compliance frontend such as:

```text
/compliance/cases/:id
/compliance/findings/:id
```

unless a later product architecture review proves a route-level distinction is necessary.

The expected design is one generic product shell plus exact Scenario UI adapters.

## 14. Frontend extension prerequisite discovered by M4

M3.5 successfully centralized Scenario-specific UI resolution, but the first adapter contract is intentionally recognized as Process Review-shaped.

The current adapter requires concepts equivalent to:

```text
RectificationPlanFields
CompletionFields
VerificationRejectFields
approve / reject verification payload builder
```

and the generic Finding page currently renders command strings equivalent to:

```text
issue
submit_plan
submit_for_verification
approve
reject
```

That is acceptable for the first Product Surface, but a materially different second Scenario must not be added by scattering new Scenario checks through the generic page.

M4 therefore freezes a **narrow frontend prerequisite**:

> Scenario-specific Finding interaction presentation must move behind the centralized exact-version Scenario UI adapter boundary before `compliance_review@1` executable Product behavior is considered complete.

## 15. Scenario interaction adapter shape

The exact TypeScript spelling is not frozen, but the conceptual design is.

A Scenario adapter may expose a scenario-specific interaction section/component receiving only:

```text
current authorized wire resource facts
normal local form state helpers
shared server command ports
shared command busy/error/refetch behavior
```

Conceptually:

```text
Generic FindingDetailPage
    │
    ├── generic title / lifecycle / participants / Actions / Activity
    │
    └── exact ScenarioInteractionSection
            │
            ├── process_review@1 interactions
            └── compliance_review@1 interactions
```

The interaction adapter may decide presentation such as:

```text
which Scenario-specific command form to show for the returned lifecycle/data
labels
Scenario payload fields
Scenario command action string
```

It must **not** become authority for:

```text
whether the user is authorized
whether a command is legal
whether a transition actually succeeds
which recipients receive a nudge
whether stale state may be ignored
```

Every mutation still goes to the generic server command and exact backend Scenario policy.

## 16. Generic command ports, not copied transport

The Scenario interaction adapter must not call raw `fetch()` or create a Scenario-specific API client family.

The generic Product Surface provides shared command ports over existing API functions, for example conceptually:

```text
transitionFinding(action, reason?)
submitRectification(action, payload)
submitVerification(action, payload)
createAction(...)
```

The adapter supplies Scenario-specific action/payload presentation while shared transport/error/refetch behavior stays centralized.

This keeps UI extensibility separate from business authority.

## 17. Exact-version UI behavior

The M3.5 exact-version rule remains unchanged.

```text
compliance_review@1 → ComplianceReviewV1 adapter
compliance_review@99 → no fallback
```

For an unknown exact UI version:

```text
generic authorized resource fields may render
Scenario-specific fields/actions fail closed
no latest/nearest/key-only fallback
```

Adding the second adapter must not weaken the existing `process_review@unknown` fail-closed behavior.

## 18. Catalog / persistence boundary

Scenario policy identity in code and persisted `Scenario` / `ScenarioVersion` catalog identity must remain consistent.

M4.1 does not pre-approve a schema migration.

If executable implementation requires a deterministic catalog bootstrap/data migration for `compliance_review@1`, that change must:

```text
add catalog data only
preserve immutable ScenarioVersion semantics
add no new schema merely for the second Scenario
```

The implementation Gate must explicitly show how code-defined policy identity and persisted catalog identity are paired.

## 19. Process Review is a regression oracle

M4 succeeds only if `process_review@1` remains unchanged in behavior.

The second Scenario must not force simplification of Process Review invariants just to manufacture a common denominator.

In particular preserve existing behavior including:

```text
Process Review issue requirements
Action completion before verification
rectification Submission validation
reviewer verification
recipient policy
M3/M3.5 acceptance
```

The correct abstraction supports both policies; it does not weaken the first one.

## 20. M4.1 scope

This Gate may change only documentation:

```text
docs/architecture/roadmap.md
docs/architecture/m4-1-second-scenario-selection-contract.md
docs/architecture/m4-1-acceptance.md
```

M4.1 Gate must not contain:

```text
src/** executable changes
web/** executable changes
alembic migration
OpenAPI change
package / lockfile change
workflow / CI change
```

No executable second-Scenario work begins until this Gate is reviewed and passed.

## 21. Explicit non-goals

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

## 22. Architecture success condition

M4 succeeds only when the repository can contain two materially different real Scenario policies while a reviewer can still say:

```text
Review Core is generic.
HTTP application services are generic.
Workbench/Management/Notification/Reminder remain shared.
Product routes remain shared.
Scenario differences are concentrated in exact Scenario policy + UI adapter modules.
```

The second Scenario is an architecture test, not a reason to generalize everything.
