# M5.5 Controlled Pilot Hardening

## Gate status

This document is the independently executable M5.5 Architecture / Acceptance
Gate. It is governed by the M5 parent charter and covers only final controlled
pilot proof for the already delivered M5.1–M5.4 capabilities. It does not
authorize production deployment or a new product capability.

The Gate is intentionally separate from the M5.4 administration Gate. No
M5.4 file is reopened by this slice.

## Goal

Prove that a clean, multi-user organization can use the integrated M5 path with
the two supported exact Scenario versions, recover from ordinary creation and
credential failures, and remain isolated from another organization. The proof
must run against the real PostgreSQL database, FastAPI service and React pages
and must be reproducible from the repository's canonical commands.

## Existing semantics to preserve

- `process_review@1` and `compliance_review@1` remain the only supported M5
  Scenario versions.
- Exact `(scenario_key, scenario_version)` resolution remains mandatory; no
  `latest`, nearby-version, key-only or client-created fallback is acceptable.
- The backend remains the authorization and validation authority for catalog,
  plans, cases, teams, administration and credentials.
- Organization isolation applies to every object used by the pilot proof.
- A platform `system_admin` does not receive ReviewCase or Scenario business
  permission merely from that platform role.
- The plan-first checkpoint remains the only supported creation sequence:
  create a plan, persist its returned ID, then create a case using that ID.
  A case retry must not create another plan.
- Case team removal and user deactivation continue to protect the last
  effective manager and leave no partial state on conflict or failure.
- Administrator credential reset continues to revoke sessions, require the
  existing forced password-change flow, and avoid exposing the temporary
  password or its hash.
- M5.5 does not change persistence schema, authentication model, or business
  lifecycle semantics.

## Pilot evidence slice

The implementation is an evidence-hardening slice. It may add a deterministic
real-browser fixture, a real-browser spec, focused integration/API assertions,
and the existing frontend command registration required to execute that spec
in CI. It must not add a new production route or domain aggregate merely to
make the test pass.

The fresh real-browser journey must prove, in one reproducible acceptance
path:

1. an empty migrated database can bootstrap the first organization and
   system administrator through the existing bootstrap path;
2. the two exact code-defined Scenario versions can be published through the
   existing exact publication path and appear in the administrator status;
3. the administrator can create the pilot department and ordinary users;
4. a newly created user can log in, complete the existing first-login password
   change, and reach business pages;
5. the user can create a `process_review@1` plan and case, then a
   `compliance_review@1` plan and case, with exact IDs and scenario payloads;
6. the plan-first page can be refreshed after the plan checkpoint and can
   retry a failed case request without posting the plan again;
7. authorized users can add and remove Case members, while the last-effective-
   manager conflict leaves the Case and activity state intact;
8. a second same-organization user can use the permitted business flow, while
   an ordinary user without the Case permission receives a safe denial;
9. cross-organization case, plan, catalog, candidate and administrator
   requests do not reveal names or object data, and an invalid role is
   rejected without candidate data;
10. an administrator credential reset revokes the user's previous session and
    sends the user through the existing forced password-change flow; and
11. the final result is visible in a Review Bundle and is executed by the
    exact-head GitHub Actions workflow.

The fixture must use stable, unique IDs and names, be safe to run after the
existing real-browser foundation fixtures, and must not depend on the order of
unrelated tests. It must exercise the existing CLI/service bootstrap and exact
publication behavior rather than silently inserting a second, untested source
of Scenario truth.

## Failure and recovery proof

The browser proof must inject one controlled network failure during the Case
step after a plan has been created. The UI must keep the persisted plan
checkpoint, show a safe retry state, and a successful retry must issue only
the Case request. A page refresh or direct re-entry must resolve the plan by
its exact ID and never guess by title.

The credential recovery proof must use two browser contexts for the target
user and administrator. After reset, the old target context must no longer be
authorized, the temporary password must not appear in any page text, URL or
response body, and the next login must enter the existing forced password
change page. The browser test must not log or snapshot secret values.

## No migration / no new architecture rule

No database migration, new persistence model, generic Scenario builder,
dynamic form engine, recovery subsystem, or CI workflow redesign is authorized.
If a missing schema capability, new production route, authorization semantic,
or concurrency model is required, stop implementation and reopen this Gate.
If the existing canonical `test:browser:real` command needs only its source
file list extended, `web/package.json` may be changed; the workflow remains the
same.

## Scope proposal for implementation review

After this Gate passes, the implementation scope may be expanded only to the
following narrow paths:

- `.easyaudit/development-state.json`;
- this Gate and its acceptance document;
- `tests/api/test_m5_5_*.py` and
  `tests/integration/test_m5_5_*.py` for final cross-slice assertions;
- `web/package.json` for the existing canonical real-browser command;
- `web/tests/browser/real-m5-5.spec.ts` and
  `web/tests/browser/seed_m5_5_real_acceptance.py`; and
- a narrowly justified existing test fixture or source file only if the
  independent Gate review identifies a regression in already authorized M5
  behavior and explicitly expands the state scope.

The following remain forbidden: `alembic/**`, `.github/workflows/**`,
production deployment, authentication or router redesign, notifications,
workbench, evidence storage, dashboards, scheduling, custom Scenario
authoring, new business permissions, and unrelated refactoring.

## Review and evidence requirements

Before implementation review, Codex must run the focused M5.5 tests and
generate `.easyaudit-review/` with `python scripts/easyaudit_gate.py bundle`.
Before final review, it must run:

```text
python scripts/easyaudit_gate.py check --require-clean --require-bundle
```

The final candidate must also have exact-head GitHub Actions evidence for the
backend, frontend and real PostgreSQL + FastAPI + React browser jobs. A local
browser pass without the corresponding GitHub run is not final evidence.

The C2C session for this slice is independent from M5.4. Codex records each
iteration before requesting review. A C2C `DONE` result closes only the inner
loop; it never authorizes merge.

## Gate lifecycle

```text
GATE_DRAFT -> GATE_REVIEW -> IMPLEMENTATION -> FINAL_REVIEW
-> MERGE_AUTHORIZED -> MERGED
```

Every transition is recorded in the outer state file. Merge requires a fixed
candidate SHA, no open P1/P2, complete Review Bundle, green exact-head CI and
the user's explicit merge authorization already recorded for this workflow.
