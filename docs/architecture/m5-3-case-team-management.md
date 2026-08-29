# M5.3 Case Team Management

## Gate status

This document is the independently executable M5.3 Architecture / Acceptance
Gate. It is governed by the M5 parent charter and authorizes only Case team
management after its Architecture / Acceptance Review passes. M5.4 and M5.5
remain out of scope.

## Goal

Let an authorized Case manager search eligible organization users, add them to
one ReviewCase with an exact Scenario role, and remove an existing membership
without leaving the Case without an effective manager. The feature extends the
existing Case detail surface and reuses the existing add and member-read
contracts.

## Existing business semantics to preserve

- The backend remains authoritative for Case visibility and
  `manage_case_members` authorization.
- The current exact Scenario policies remain the source of Case role semantics.
  For both `process_review@1` and `compliance_review@1`, the Case roles are
  `lead`, `auditor`, `reviewer`, and `observer`; the current policy grants
  `manage_case_members` to the `lead` role.
- A platform `system_admin` has no Case business shortcut. Its platform role is
  deliberately absent from Scenario authorization facts.
- Organization isolation, active-user rules and exact Scenario version
  resolution remain server-side rules.

## API contract

Add the bounded Case-scoped candidate read:

```text
GET /api/v1/review-cases/{case_id}/member-candidates
    ?role_key={role_key}&q={query}&limit={limit}
```

The response is a JSON list of presentation-safe candidates:

```json
[
  {
    "user_id": "<uuid>",
    "display_name": "Auditor User"
  }
]
```

The endpoint must check `manage_case_members` before loading or returning any
candidate display name. It returns only active `ordinary_user` accounts in the
Case organization, excludes a user already assigned the requested role, uses
case-insensitive substring matching on a trimmed `q`, has deterministic name /
ID ordering, and enforces `1 <= limit <= 20` at the API boundary.

`role_key` is validated against the Case's persisted exact
`scenario_key@scenario_version`; no latest, nearest-version or key-only
fallback is permitted. Invalid roles are rejected and no names are returned.

Continue using:

```text
POST /api/v1/review-cases/{case_id}/members
```

and add:

```text
DELETE /api/v1/review-cases/{case_id}/members/{user_id}?role_key={role_key}
```

Removal returns the removed `CaseMember` representation on success. It returns
a clear conflict response when removing the last effective manager would make
the Case unmanaged. Missing Case or membership remains a normal not-found
response; authorization remains a forbidden response.

## Atomic removal and concurrency boundary

The removal use case must execute in one request transaction:

1. lock the authoritative ReviewCase row for update;
2. re-read the exact Scenario policy, current actor authorization and current
   memberships after the lock;
3. validate the exact role and membership;
4. count effective active users whose Case roles grant
   `manage_case_members` under that exact policy;
5. reject removal if the target is the last such manager;
6. delete exactly the requested membership; and
7. append `review_case.member_removed` with actor, target user and role
   metadata.

The member delete and Activity append share the surrounding transaction. A
conflict or persistence failure must leave both the membership and Activity
unchanged. The Case row lock serializes concurrent removals of distinct final
managers: one request may succeed, and the other must re-read the state and
return a conflict rather than leave zero effective managers.

No migration, new persistence model, Case aggregate or general concurrency
framework is authorized by this Gate. If implementation needs one, stop and
return to Gate review.

## Frontend seam

The Case detail page consumes the exact Scenario adapter's Case role display
definitions. The adapter owns labels and exact role keys; the page must not
invent a role, infer roles from a display label, or use a fallback adapter.

The team panel must support:

- selecting an exact role and searching candidates through the Case-scoped
  endpoint;
- adding a selected candidate through the existing POST contract;
- listing current members with role labels;
- removing a membership through the DELETE contract;
- refreshing the member list after a successful mutation; and
- displaying forbidden, invalid-role, not-found and last-manager conflict
  responses without hiding the current team.

When the current user lacks management permission, the UI may show a safe
unavailable state, but it must never obtain names from an administrator user
list or infer permission from the platform role.

## Scope

Implementation is limited to:

- `src/easyaudit_next/api/review_contracts.py` and
  `src/easyaudit_next/api/review_planning.py`;
- the Review Planning application, mutation results, repository protocol and
  SQLAlchemy repository needed for exact candidate reads and locked member
  removal;
- the existing composition wiring if required;
- the Case-scoped context/query presentation types if required;
- exact frontend Scenario role display definitions, Product API calls, the
  existing Case detail team panel and focused tests;
- M5.3 integration and real browser acceptance seed/test coverage; and
- the existing canonical frontend command registration if a new real browser
  file must be added.

No `alembic/**`, deployment, authentication, administrator, notification,
workbench, evidence, dashboard, or generic Scenario-builder work is included.
No Scenario business permission or role meaning may be changed.

## Acceptance summary

- unauthenticated, inactive, cross-organization and unauthorized callers do
  not receive candidate names;
- a system administrator without Case business authority cannot bypass the
  Case permission check;
- inactive, cross-organization and system-admin candidate accounts are absent;
- exact `process_review@1` and `compliance_review@1` roles are accepted;
- an unknown or mismatched role is rejected without a fallback;
- limit never exceeds 20 and search ordering is deterministic;
- add continues to create the requested exact membership;
- valid removal deletes only the requested membership and appends the exact
  `review_case.member_removed` Activity;
- the last effective manager cannot be removed;
- concurrent final-manager removals cannot produce an unmanaged Case;
- failed removal leaves membership and Activity state unchanged; and
- the real browser flow covers search, add, remove, permission failure and
  last-manager protection against real PostgreSQL, FastAPI and React.

## Outer lifecycle

```text
GATE_DRAFT -> GATE_REVIEW -> IMPLEMENTATION -> FINAL_REVIEW
-> MERGE_AUTHORIZED -> MERGED
```

