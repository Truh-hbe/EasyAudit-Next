# M5.1 Review Catalog and Scenario Readiness Acceptance

## Scenario publication

- A registered `process_review@1` publishes successfully for an existing
  organization.
- A registered `compliance_review@1` publishes successfully for an existing
  organization.
- Repeating either exact publication fails deterministically.
- An unknown key or version fails closed.
- Publication never selects a latest version or creates an arbitrary runtime
  policy.
- Existing Scenario and ScenarioVersion tables are reused; no migration is
  expected or pre-approved for this slice.

## Clean environment

The integration journey must prove:

```text
alembic upgrade head
-> bootstrap organization and administrator
-> publish process_review@1
-> publish compliance_review@1
-> authenticate as a business user
-> GET /api/v1/review-catalog
```

Both exact versions must be visible and ready for later Case creation. A second
organization must not inherit the first organization's publications.

## Catalog contract

- The endpoint requires the existing business identity.
- An unauthenticated request returns the existing authentication error.
- A must-change-password user is rejected by existing identity rules.
- Only active, persisted, published, Registry-known exact versions appear.
- Eligibility uses the exact Scenario Case-creation decision for the current
  actor; no Product-only planner permission is introduced.
- Response items contain only `scenario_key`, `scenario_version`, and
  `display_name`.
- Ordering is deterministic.
- Unknown or stale exact versions are omitted with no fallback.
- Cross-organization data is never returned.

## Frontend exact-version seam

- The `process_review@1` adapter renders `area_code` and `review_type` and
  builds exactly those keys in `scenario_data`.
- The `compliance_review@1` adapter renders `standard_reference` and
  `scope_summary` and builds exactly those keys in `scenario_data`.
- An unknown key/version has no latest, nearest, or key-only adapter fallback.
- Adapter code does not decide authorization or replace backend validation.

## Verification commands

The Gate candidate must pass:

```text
python scripts/easyaudit_gate.py check
pytest tests/tooling/test_easyaudit_gate.py
```

After implementation, the focused backend, API, frontend, and integration tests
must pass and any new browser acceptance must be included by the canonical CI
script rather than only by a local command.

## Out of scope

This acceptance does not cover ReviewPlan/ReviewCase creation UI, member search
or removal, administrator React pages, credential reset, scheduler/deployment,
or any generic/dynamic Scenario form engine.
