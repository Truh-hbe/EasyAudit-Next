# M5.2 Plan-first Planning Surface Acceptance

## Plan-first journey

An authenticated active organization user can:

1. open `/review-plans/new`;
2. read the server-backed exact review catalog;
3. enter a plan title and optional planned dates;
4. create the ReviewPlan;
5. continue to `/review-plans/{planId}/review-cases/new`;
6. reload the page and recover the plan by `GET /review-plans/{planId}` and
   the current creatable catalog by `GET /review-catalog`;
7. enter an explicit Case title and the exact scenario fields;
8. create the ReviewCase with the checkpointed plan ID; and
9. immediately land on `/review-cases/{caseId}`, where the existing detail
   route performs the authoritative Case GET.

Both journeys must work with real API requests for:

```json
process_review@1:
{"area_code":"area-a","review_type":"standard"}
```

```json
compliance_review@1:
{"standard_reference":"standard-a","scope_summary":"pilot scope"}
```

## Recovery and idempotency boundary

- The plan form submits one Plan request and records the returned ID in the
  route before the Case step begins.
- Reloading or directly entering the Case step performs both a Plan GET and a
  current review-catalog GET, and never repeats Plan creation.
- A definitive rejected Case request leaves the Plan checkpoint intact and
  may be corrected and retried using the same Case payload contract.
- A timeout, disconnect or other ambiguous transport outcome after Case
  dispatch leaves the Plan checkpoint intact, shows Case creation status as
  unknown, and never automatically repeats the Case request.
- A missing Plan, 403, 404 or invalid server response stops the Case step with
  a useful error and no Case POST.
- If the Plan response is lost after server success, the UI does not search by
  title or create a guessed duplicate; this accepted limitation is visible in
  the controlled-pilot evidence.
- Plan dates are not copied to Case dates. M5.2 sends Case dates omitted/null.

## Exact adapter and fail-closed rules

- The catalog controls which exact key/version choices are presented.
- `process_review@1` renders only `area_code` and `review_type`.
- `compliance_review@1` renders only `standard_reference` and `scope_summary`.
- Missing exact adapter resolution disables creation and never falls back to
  latest, nearest version or key-only behavior.
- Adapter code builds `scenario_data`; it does not make authorization
  decisions or bypass backend validation.

## Case payload contract

The Case step requires an explicit non-empty title. It must send:

```json
{
  "plan_id": "<checkpointed plan id>",
  "scenario_key": "<exact catalog key>",
  "scenario_version": 1,
  "title": "<explicit case title>",
  "scenario_data": "<exact adapter output>"
}
```

The Plan title is never reused or transformed into the Case title. No Plan
date inheritance is implicit in this slice.

## Permissions and errors

- Unauthenticated users follow the existing login flow.
- Must-change-password users follow the existing credential-remediation flow.
- Active organization users retain the backend's existing Plan permissions.
- The page does not add an administrator-only or manager-only restriction.
- Cross-organization or unavailable Plans cannot be used for Case creation.
- API validation and authorization errors are rendered without losing the
  checkpoint or causing an extra Plan request.

## Required verification

The slice must include:

- frontend component tests for both steps, exact adapters, refresh recovery,
  definitive Case-only retry, ambiguous Case no-retry and fail-closed adapter
  handling;
- backend/integration coverage proving existing Plan/Case endpoints receive the
  correct plan ID and exact scenario data;
- a real browser acceptance test using PostgreSQL, FastAPI and React that
  creates both scenario types and exercises refresh plus deterministic
  recoverable Case rejection; ambiguous Case transport must be covered by a
  focused client test;
- the browser test must be reached by the repository's canonical CI command,
  not only a local command.

## Out of scope

Case member search/removal, administrator pages, credential reset, custom
scenarios, dynamic forms, evidence storage, dashboards, deployment and any
database migration are not M5.2 acceptance requirements.
