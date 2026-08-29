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
- An active same-organization `system_admin` may still be explicitly assigned
  a valid Case role through the existing add endpoint. If assigned `lead`, that
  persisted Case membership grants Case business authority; the platform role
  itself never does. Candidate search must still omit system-admin accounts.
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
2. re-read current memberships and lock all relevant User rows in deterministic
   User-ID order;
3. re-read the exact Scenario policy and rebuild the current actor
   authorization after the locks are held;
4. validate the exact role and membership;
5. construct `remaining_memberships` by removing exactly the requested
   `(case_id, user_id, role_key)`;
6. evaluate the exact Scenario authorization policy for the complete remaining
   role set of each active member, collect unique effective manager User IDs,
   and reject if that set is empty;
7. delete exactly the requested membership; and
8. append `review_case.member_removed` with actor, target user and role
   metadata.

The last-manager rule is a post-removal invariant, not a target-user shortcut.
It counts unique active User IDs whose complete remaining Case-role grants
allow `manage_case_members` under the persisted exact Scenario policy. Thus a
sole manager with both `lead` and `observer` may lose `observer`, but may not
lose `lead`; the algorithm must not hard-code `lead` or count memberships.

The member delete and Activity append share the surrounding transaction. A
conflict or persistence failure must leave both the membership and Activity
unchanged. The Case row lock serializes same-Case removals. Every waiter must
re-read the memberships and actor authorization after acquiring the lock. A
concurrent result is safe when at most one deletion can reduce the effective
manager set to its boundary, at least one effective manager remains, and a
rejected transaction creates no `review_case.member_removed` Activity. The
second response may be HTTP 409 when the actor is still authorized but the
requested deletion would remove the final manager, or HTTP 403 when the first
committed deletion removed that actor's management authority.

Because manager effectiveness includes account activity, the existing user
deactivation service must participate in the same narrow lock protocol for
affected Cases: lock affected Case rows in deterministic Case-ID order, then
lock/reload relevant User rows, evaluate the post-deactivation manager set, and
reject a deactivation that would leave any affected Case unmanaged. Removal and
deactivation use the same Case-before-User order to avoid deadlocks. This is a
small invariant-preserving service change only; no M5.4 administrator page is
authorized here.

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
- refreshing the member list and Case Activity after a successful mutation; and
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
- the existing platform administration service and narrow User repository
  locking capability only as required to serialize Case-manager
  deactivation; no administrator UI is part of this slice;
- exact frontend Scenario role display definitions, Product API calls, the
  existing Case detail team panel and focused tests;
- `openapi/openapi.json` as the committed API contract baseline;
- M5.3 integration and real browser acceptance seed/test coverage; and
- the existing canonical frontend command registration if a new real browser
  file must be added.

No `alembic/**`, deployment, authentication, administrator UI, notification,
workbench, evidence, dashboard, or generic Scenario-builder work is included.
No Scenario business permission or role meaning may be changed.

## Acceptance summary

- unauthenticated, inactive, cross-organization and unauthorized callers do
  not receive candidate names;
- a system administrator without Case business authority cannot bypass the
  Case permission check;
- inactive, cross-organization and system-admin candidate accounts are absent;
- an explicitly assigned active system-admin Case member derives authority
  only from the persisted Case role and remains subject to the same removal
  invariant;
- exact `process_review@1` and `compliance_review@1` roles are accepted;
- an unknown or mismatched role is rejected without a fallback;
- limit never exceeds 20 and search ordering is deterministic;
- add continues to create the requested exact membership;
- valid removal deletes only the requested membership and appends the exact
  `review_case.member_removed` Activity;
- the post-removal effective-manager set is never empty;
- concurrent final-manager removals can produce only the authorized 409/403
  outcomes and cannot produce an unmanaged Case;
- concurrent member removal and manager deactivation cannot produce an
  unmanaged Case;
- failed removal leaves membership and Activity state unchanged; and
- the real browser flow covers search, add, remove, permission failure and
  last-manager protection against real PostgreSQL, FastAPI and React.

## Outer lifecycle

```text
GATE_DRAFT -> GATE_REVIEW -> IMPLEMENTATION -> FINAL_REVIEW
-> MERGE_AUTHORIZED -> MERGED
```
