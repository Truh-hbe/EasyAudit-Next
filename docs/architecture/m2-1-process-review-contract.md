# M2.1 — Process Review Contract & Workflow

## Goal

M2.1 proves that `process_review@1` can explain ReviewCase, Finding, ActionItem,
Submission, scenario-specific data, creation behavior, relationship roles, and business
authorization without teaching Review Core what Process Review is.

This increment is domain-only. It intentionally adds no Review Core HTTP write API, database
migration, dashboard, notification, scheduler, or frontend behavior.

## Scenario capability boundary

`ScenarioPolicy` exposes typed capabilities for:

- `case_creation`
- `case_workflow`
- `finding_workflow`
- `action_workflow`
- `authorization`
- `submission_policy`

It also exposes versioned Role Specifications and owns validation of Case and Finding scenario data
through `validate_case_input()` and `validate_finding_input()`.

Review Core defines only the capability Protocols and generic contexts/decisions. Concrete action
names and Process Review rules live under `easyaudit_next.scenarios.process_review`.

## ReviewPlan and ReviewCase creation

`ReviewPlan` is a cross-Scenario Core planning container. Its creation is deliberately not decided by
the scenarios later placed under the plan. Core planning authorization permits an active user of the
organization to create a ReviewPlan. Creating a plan records `created_by`; it does not mint a
Scenario business role.

ReviewCase creation is Scenario-owned. `process_review@1` defines `create_case` and permits it for
an active user of the organization. The Case creation decision requires the application service to
atomically create:

1. the ReviewCase in `draft` lifecycle;
2. the creator's `CaseMember(role_key="lead")` relationship; and
3. the `review_case.created` Activity.

Platform `system_admin` is not a substitute for this Scenario permission and is not automatically a
lead.

## Versioned Role Specifications

A role is not only a string key. Each Scenario version declares:

- the role key;
- allowed actor kinds (`user` or `department`); and
- the relationship source through which the current user may derive authority (`direct` or
  `department_membership`).

Process Review v1 freezes these rules:

| Relationship | Role | Actor | Permission source |
|---|---|---|---|
| CaseMember | `lead` | User | direct |
| CaseMember | `auditor` | User | direct |
| CaseMember | `reviewer` | User | direct |
| CaseMember | `observer` | User | direct |
| FindingParticipant | `responsible_department` | Department | department membership |
| FindingParticipant | `owner` | User | direct |
| FindingParticipant | `collaborator` | User | direct |
| ActionAssignee | `primary` | User | direct |
| ActionAssignee | `collaborator` | User | direct |

A Department `responsible_department` relationship expands visibility only. Formal rectification
writes require an explicit User relationship. Process Review v1 does not permit Department
ActionAssignee relationships; therefore department membership can never produce
`update_assigned_action` authority in this Scenario version.

## ReviewCase lifecycle

```text
DRAFT --schedule--> SCHEDULED --start--> IN_PROGRESS
  --finish_fieldwork--> AWAITING_CLOSURE --close--> CLOSED

DRAFT / SCHEDULED --cancel(reason)--> CANCELLED
```

`close` is rejected until every Finding is terminal (`closed` or `voided`). The application layer
will calculate that fact and pass it through `ReviewCaseTransitionContext` in M2.2/M2.5.

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

## Formal Submission decisions

A formal Submission is not an independent CRUD write. `SubmissionPolicy.decide()` receives the
current Finding lifecycle, requested business action, Submission purpose/payload, and workflow
facts. It returns a structured decision containing:

- required business permission;
- target Finding lifecycle;
- Activity event type; and
- an explicit atomic-write requirement.

The future application service must persist the Submission, lifecycle change, and Activity in one
transaction. There must not be separate public operations that can leave those records inconsistent.

Process Review v1 freezes the following pairs:

| Request action | Submission | Required current lifecycle | Target |
|---|---|---|---|
| `submit_plan` | rectification / `stage=plan` | `rectifying` | `rectifying` |
| `submit_for_verification` | rectification / `stage=completion` | `rectifying` | `verifying` |
| `approve` | verification / `result=approved` | `verifying` | `closed` |
| `reject` | verification / `result=rejected` | `verifying` | `rectifying` |

`submit_for_verification` reuses the Finding workflow guard that requires at least one active Action
and all non-cancelled Actions to be done. Rejection requires a non-blank comment, which is also the
workflow rejection reason.

Every Submission remains an immutable history record; response-round counters are not introduced.

## Scenario data v1

Process Review v1 requires non-blank strings for:

- Case: `area_code`, `review_type`
- Finding: `issue_type`, `project_category`

The validators allow additional keys so future Process Review fields can be introduced deliberately
without turning Review Core columns into Scenario-specific storage.

Persistence of `scenario_data` is deliberately sequenced after this pure-domain contract.

## Dependency direction and composition root

Scenario modules may depend inward on Review Core contracts. The reverse direction is prohibited.
The architecture guard scans the complete `src/easyaudit_next` package and rejects any import of
`easyaudit_next.scenarios` outside:

- the Scenario package itself; and
- `easyaudit_next.composition`, the single composition root.

The composition root constructs `ScenarioRegistry` and registers `PROCESS_REVIEW_V1`. Review Core
and Platform therefore cannot acquire an indirect Scenario dependency even if no literal
`process_review` branch is present.

The previous text-level test that Review Core contains no `process_review` string remains as a
secondary guard, not the primary dependency rule.

## M2.1 exit gate

M2.1 is ready for Final architecture review only when CI proves all of the following:

- ReviewPlan creation is Core-owned and tested;
- Process Review Case creation permission and automatic first lead are Scenario-owned and tested;
- all Case/Finding/Action relationship roles have actor/source specifications;
- department-derived relationships cannot accidentally grant Action write authority;
- formal Submission decisions bind payload, action, lifecycle, permission, and Activity semantics;
- the atomic write requirement is explicit in the contract; and
- Core/Platform cannot import Scenario modules outside the composition root.

M2.2 must not start until this gate is reviewed and accepted.
