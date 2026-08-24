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
rules, authorization, and lifecycle calculation to that policy. Review Core contains no
Process Review branch or Scenario import.

Process Review v1 permits Case `lead` and `auditor` roles to create, issue, void, and manage
Finding participants. Direct `owner` and `collaborator` User relationships, and membership in the
`responsible_department`, grant visibility only at this stage. A Department relationship cannot
produce Finding write authority.

All User and Department participant targets must be active and belong to the Finding's
organization. Repository reads continue to require both `organization_id` and entity id.

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

M2.3 intentionally exposes only transitions from `open` to `rectifying` or `voided`. Later
rectification and verification transitions must be driven by the atomic Submission decision path
introduced in M2.4/M2.5; they are not available as standalone lifecycle writes.
