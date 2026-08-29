# M5.2 Plan-first Planning Surface

## Gate status

This is the independently executable M5.2 Architecture / Acceptance Gate. It
is governed by the M5 parent charter and does not authorize M5.3 or later
product work.

## Goal

Let an active organization user create a ReviewPlan first, then create one
supported ReviewCase from that plan through a recoverable two-step product
flow. The flow must use the existing ReviewPlan and ReviewCase APIs and the
exact-version scenario adapters established by M5.1.

The user-facing routes are:

```text
/review-plans/new
/review-plans/{planId}/review-cases/new
```

The plan ID in the second route is the durable client checkpoint. Refreshing or
re-entering that route must re-read the plan from the server before showing
the case form.

## Architecture

```text
review catalog
  -> exact scenario/version adapter
  -> POST /review-plans
  -> planId URL checkpoint
  -> GET /review-plans/{planId}
  -> POST /review-cases with planId + adapter-built scenario_data
  -> GET /review-cases/{caseId}
  -> case detail
```

The frontend owns navigation, presentation and checkpoint recovery only. The
backend remains authoritative for authentication, organization isolation,
plan visibility, scenario publication, scenario validation and Case creation
authorization.

## Required behavior

1. The first step loads the authenticated user's current review catalog and
   collects the plan title and dates.
2. Submitting the first step makes exactly one `POST /api/v1/review-plans`.
   The returned `plan_id` is immediately placed in the second route before
   the case request is submitted.
3. The second step loads `GET /api/v1/review-plans/{plan_id}` on entry and
   refresh. A missing, unauthorized or unavailable plan stops the flow and
   does not submit a Case.
4. The second step selects an exact catalog identity and resolves the exact
   adapter. The adapter renders its fields and builds `scenario_data`; the
   page never uses latest, nearby-version or key-only fallback.
5. Submitting the second step makes one `POST /api/v1/review-cases` with the
   checkpointed `plan_id`. On failure, only the Case request is retryable; the
   UI must not create another ReviewPlan.
6. After Case creation succeeds, the page re-reads the returned Case and
   navigates to `/review-cases/{caseId}`.
7. A network ambiguity after a successful Plan request is a documented
   controlled-pilot limitation. The client must not guess a Plan by title or
   silently issue a second Plan request.
8. Existing plan authorization is preserved: any active organization user
   allowed by the backend may use the flow. The product UI must not add an
   administrator-only or manager-only rule.

## Exact scenario surface

M5.2 consumes only these M5.1 identities and fields:

- `process_review@1`: `area_code`, `review_type`;
- `compliance_review@1`: `standard_reference`, `scope_summary`.

An exact catalog item without a matching adapter is visibly unavailable for
creation. No dynamic form engine or generic scenario builder is introduced.

## Scope

Allowed work is limited to the planning routes, their API client calls,
scenario-adapter consumption, focused tests, and real browser acceptance for
this flow. The existing backend interfaces are reused:

```text
POST /api/v1/review-plans
GET  /api/v1/review-plans/{plan_id}
POST /api/v1/review-cases
GET  /api/v1/review-cases/{case_id}
GET  /api/v1/review-catalog
```

No new merge-style creation endpoint, aggregate, persistence model, migration,
authorization semantic, team-management operation, administrator page or
scenario version is part of this Gate.

## Acceptance summary

- both exact scenarios can be created through the plan-first UI;
- the plan ID survives route refresh and recovers from the server;
- a failed Case request retries only the second step;
- exact adapter resolution fails closed;
- server errors and permission errors are visible and recoverable;
- organization and existing business permissions remain server-controlled;
- unit/component, integration and real PostgreSQL/FastAPI browser tests are
  included in the canonical CI command.

## Outer lifecycle

```text
GATE_DRAFT -> GATE_REVIEW -> IMPLEMENTATION -> FINAL_REVIEW
-> MERGE_AUTHORIZED -> MERGED
```

This Gate authorizes only the M5.2 planning surface after its Architecture /
Acceptance review passes.
