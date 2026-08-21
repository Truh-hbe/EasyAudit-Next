# M2.2 — Review Planning & Case

## Goal

M2.2 is the first application/persistence realization of the M2.1 Scenario contract. It exposes
authenticated ReviewPlan, ReviewCase, CaseMember, and ReviewCase transition APIs without adding
Process Review branches to Review Core.

## Scope

- ReviewPlan create/list/get using the Core planning authorization policy.
- ReviewCase create/list/get using the exact published ScenarioVersion.
- ReviewCase planning timestamps and version-owned `scenario_data` persistence.
- Automatic creator membership defined by the Scenario CaseCreationDecision.
- CaseMember list/add with Scenario RoleSpecification validation.
- ReviewCase lifecycle transitions through the Scenario workflow capability.
- Append-only Activity for Case creation, membership additions, and transitions.
- Organization-scoped repository reads.
- Business API gate for local users whose credential still requires a password change.

Finding, ActionItem, Submission, Evidence, and Case closure orchestration are not added here.

## Creation transaction

For `process_review@1`, Case creation means one database transaction containing:

1. the new ReviewCase in `draft`;
2. the creator's `lead` CaseMember relationship;
3. the `review_case.created` Activity.

The application service deliberately flushes these writes but never commits. The request-scoped
SQLAlchemy Unit of Work owns commit/rollback. PostgreSQL integration tests force the third write to
violate a real database CHECK constraint after the first two writes have flushed, then verify from a
fresh Session that no Case or lead membership remains.

This is the persistence proof of the M2.1 `CaseCreationDecision`; no Scenario-specific transaction
logic is allowed in Review Core.

## API shape

State is not writable through ordinary PATCH. M2.2 exposes:

- `POST /api/v1/review-plans`
- `GET /api/v1/review-plans`
- `GET /api/v1/review-plans/{id}`
- `POST /api/v1/review-cases`
- `GET /api/v1/review-cases`
- `GET /api/v1/review-cases/{id}`
- `GET /api/v1/review-cases/{id}/members`
- `POST /api/v1/review-cases/{id}/members`
- `POST /api/v1/review-cases/{id}/transitions`

M2.2 supports schedule, start, finish_fieldwork, and pre-start cancellation according to the exact
Scenario workflow. `close` remains blocked because Finding-terminal orchestration belongs to M2.5.

## Organization boundary

Review Core read methods require `organization_id` together with object id. A UUID alone is never an
authorization boundary. Cross-organization reads therefore resolve as not found before business-role
authorization is evaluated.
