# M2.3 — Finding Lifecycle & Participants

## Scope

M2.3 implements the generic Review Core application path for:

- create, list, and get Finding;
- persist version-owned Finding `scenario_data`;
- add and list typed FindingParticipant relationships;
- derive visibility from direct User and Department membership relationships; and
- perform the first Finding lifecycle transitions through the exact Case ScenarioVersion.

M2.3 does not implement ordinary Finding PATCH/delete, ActionItem, Submission, Evidence,
verification, reopening, or Case closure. A Finding is invalidated through the Scenario `void`
transition rather than physical deletion.

## Scenario and authorization boundary

The application service resolves the Scenario policy from the parent ReviewCase's immutable
`(ScenarioKey, ScenarioVersion)`. It delegates Finding payload validation, participant role actor
rules, authorization, operation invariants, and lifecycle calculation to that policy. Review Core
contains no Process Review branch or Scenario import.

Authorization and operation validity are deliberately separate concerns. Review Core derives the
current actor's relationship grants for authorization, while it also supplies a Scenario-neutral
`FindingOperationContext` containing persisted business facts such as:

- parent ReviewCase lifecycle;
- current Finding lifecycle, when a Finding already exists;
- the set of FindingParticipant role keys currently present;
- action-summary fields reserved for later rectification stages; and
- the operation reason when supplied.

The concrete Scenario decides what those facts mean. The generic service does not compare against
Process Review lifecycle values and does not know Process Review participant role names.

Process Review v1 permits Case `lead` and `auditor` roles to create, issue, void, and manage
Finding participants. Direct `owner` and `collaborator` User relationships, and membership in the
`responsible_department`, grant visibility only at this stage. A Department relationship cannot
produce Finding write authority.

Process Review v1 freezes these M2.3 operation invariants:

- new Findings may be created only while the parent Case is `in_progress`;
- an existing open Finding may be issued or voided while the Case is `in_progress` or
  `awaiting_closure`;
- `issue` requires both an `owner` User and a `responsible_department` Department before the
  Finding may enter `rectifying`;
- `awaiting_closure` therefore permits finalizing an already-created open Finding but does not
  permit discovering a new one; and
- ordinary participant management is frozen once the Finding is `closed` or `voided`.

The `awaiting_closure` rule is intentional: fieldwork completion stops new Finding discovery while
still allowing an already-recorded open Finding to have responsibility completed and be issued or
voided, avoiding an artificial dead-end during Case closure.

All User and Department participant targets must be active and belong to the Finding's
organization. Repository reads continue to require both `organization_id` and entity id.

## API error semantics

The API distinguishes validation from concurrency:

- authorization failure: 403;
- organization-scoped lookup miss: 404;
- Scenario data, actor-role, workflow, and Finding operation validation failure: 422; and
- PostgreSQL CAS loss or persistence conflict: 409.

`409 Concurrent Finding transition` remains the concurrency contract.

## Persistence and lifecycle concurrency

Migration `20260824_0007` adds non-null JSONB `findings.scenario_data`, with `{}` only as the
backfill/default for pre-M2.3 rows.

Finding creation writes `finding.created`; participant creation writes
`finding.participant_added`; lifecycle changes write `finding.transitioned`. The request-scoped
database transaction is the unit of work for each entity change plus its Activity.

Lifecycle transitions use compare-and-swap:

```text
UPDATE findings
SET lifecycle = :target
WHERE organization_id = :organization_id
  AND id = :finding_id
  AND lifecycle = :expected_lifecycle
```

No matching row produces `409 Concurrent Finding transition`, and no transition Activity is
written. PostgreSQL double-Session coverage proves that two requests reading `open` cannot both
record the same transition.

PostgreSQL Finding fixtures follow the real Process Review chain and advance a newly created Case
through `schedule` and `start` before creating a Finding. Tests also prove that responsibility must
exist before `issue` and that the Scenario capability, not Review Core branching, owns the rule.

M2.3 intentionally exposes only transitions from `open` to `rectifying` or `voided`. Later
rectification and verification transitions must be driven by the atomic Submission decision path
introduced in M2.4/M2.5; they are not available as standalone lifecycle writes.
