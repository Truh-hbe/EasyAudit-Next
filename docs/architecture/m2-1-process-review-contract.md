# M2.1 — Process Review Contract & Workflow

## Goal

M2.1 proves that `process_review@1` can explain ReviewCase, Finding, ActionItem,
Submission, scenario-specific data, and business authorization without teaching Review Core what
Process Review is.

This increment is domain-only. It intentionally adds no Review Core HTTP write API, database
migration, dashboard, notification, scheduler, or frontend behavior.

## Scenario capability boundary

`ScenarioPolicy` now exposes five typed capabilities:

- `case_workflow`
- `finding_workflow`
- `action_workflow`
- `authorization`
- `submission_policy`

It also owns validation of Case and Finding scenario data through `validate_case_input()` and
`validate_finding_input()`.

Review Core defines only the capability Protocols and generic transition/authorization contexts.
The concrete action names and rules live under `easyaudit_next.scenarios.process_review`.

## Process Review v1 roles

CaseMember roles:

- `lead`
- `auditor`
- `reviewer`
- `observer`

FindingParticipant roles:

- `responsible_department`
- `owner`
- `collaborator`

Action assignments continue to use the Core `primary` and `collaborator` roles.

A Department `responsible_department` relationship expands visibility only. Formal rectification
writes require an explicit User relationship. Platform `system_admin` is deliberately absent from
Scenario authorization context and therefore is not implicitly a lead or reviewer.

## ReviewCase lifecycle

```text
DRAFT --schedule--> SCHEDULED --start--> IN_PROGRESS
  --finish_fieldwork--> AWAITING_CLOSURE --close--> CLOSED

DRAFT / SCHEDULED --cancel(reason)--> CANCELLED
```

`close` is rejected until every Finding is terminal (`closed` or `voided`). The Core/application
layer will calculate that fact and pass it through `ReviewCaseTransitionContext` in M2.2/M2.5.

## Finding lifecycle

```text
OPEN --issue--> RECTIFYING --submit_for_verification--> VERIFYING
VERIFYING --approve--> CLOSED
VERIFYING --reject(reason)--> RECTIFYING
OPEN --void(reason)--> VOIDED
CLOSED --reopen(reason)--> RECTIFYING
```

`submit_for_verification` requires at least one non-cancelled ActionItem and requires every
non-cancelled ActionItem to be `done`.

There is no `first_reply_submitted` lifecycle. A first reply is a rectification Submission with
`stage=plan` while the Finding remains `rectifying`.

## ActionItem lifecycle

```text
TODO --start--> IN_PROGRESS --complete--> DONE
TODO / IN_PROGRESS --cancel(reason)--> CANCELLED
DONE --reopen--> IN_PROGRESS
```

Finding is the verification object. ActionItem does not gain approved/rejected/pending-review
states.

## Submission semantics

Rectification plan:

```json
{
  "stage": "plan",
  "root_cause": "..."
}
```

Rectification completion:

```json
{
  "stage": "completion",
  "comment": "整改完成，请审核"
}
```

Verification:

```json
{
  "result": "approved",
  "comment": "..."
}
```

or:

```json
{
  "result": "rejected",
  "comment": "拒绝原因（必填）"
}
```

Every Submission remains an immutable history record; response-round counters are not introduced.

## Scenario data v1

Process Review v1 requires non-blank strings for:

- Case: `area_code`, `review_type`
- Finding: `issue_type`, `project_category`

The validators allow additional keys so future Process Review fields can be introduced deliberately
without turning Review Core columns into Scenario-specific storage.

Persistence of `scenario_data` is deliberately sequenced after this pure-domain contract.

## Architecture acceptance

Tests enforce that the `review_core/` source tree contains no `process_review` branching. Scenario
modules are included in the architecture dependency guard and may not import API, persistence,
application, FastAPI, SQLAlchemy, Alembic, or Pydantic layers.

M2.2 may now build Review planning and Case APIs by resolving the exact ScenarioVersion from the
Registry and invoking these capabilities; it must not branch on Scenario key.
