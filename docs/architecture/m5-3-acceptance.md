# M5.3 Case Team Management Acceptance

## Candidate read

For each exact supported Case scenario:

1. an authenticated active Case manager requests a valid Case role;
2. the service checks the persisted Case's exact Scenario policy and
   `manage_case_members` permission;
3. the response contains only active ordinary users in the same organization;
4. already assigned users for that role are omitted;
5. `q` performs deterministic, case-insensitive substring search; and
6. `limit=20` is the maximum accepted value.

The following must not disclose a candidate name:

- no session;
- must-change-password or inactive identity;
- Case from another organization;
- actor without the Case manager role;
- system administrator without the Case manager role; and
- a role not registered by the Case's exact Scenario version.

The candidate query must not call or reuse the administrator user-list
operation. A rejected authorization or role request is checked before any
candidate presentation data is loaded.

## Add and remove

- Both `process_review@1` and `compliance_review@1` accept the exact Case role
  keys `lead`, `auditor`, `reviewer` and `observer`.
- An invalid role is rejected by the backend even if a client sends it
  directly.
- The existing add endpoint remains the only add mutation for this slice.
- A valid DELETE removes only the requested `(case_id, user_id, role_key)`.
- The delete response identifies the removed membership.
- A successful delete creates exactly one `review_case.member_removed` Activity
  whose metadata identifies the target user and role.
- A missing membership, unauthorized actor or cross-organization target does
  not remove anything or create an Activity.

## Last-manager invariant

The creator's `lead` membership is initially present. With one effective active
manager remaining, deleting that manager returns HTTP 409 and leaves both the
membership and Activity count unchanged. If another effective manager exists,
deleting one manager succeeds. An inactive account holding a manager role does
not count as an effective actor for this protection.

Two concurrent transactions attempting to delete the final two effective
managers must result in one success and one HTTP 409 (or an equivalent
conflict), with at least one effective manager remaining and no partial
Activity.

## Frontend journey

Using a real authenticated React page:

1. open a visible Case detail page;
2. read the exact Case role definitions from the exact adapter;
3. search candidates for `lead`, `auditor`, `reviewer` and `observer` without
   exposing server-side names before authorization;
4. add one candidate and observe the member list refresh;
5. remove that membership and observe the list and Activity refresh;
6. attempt to remove the final manager and display the conflict while keeping
   the manager visible; and
7. verify a non-manager sees a safe permission error and no candidate names.

## Required verification

The slice must include:

- API/OpenAPI contract tests for candidate response and DELETE parameters;
- service/repository tests for exact role validation, organization/active-user
  filtering, permission-before-name ordering, atomic Activity behavior and
  last-manager protection;
- PostgreSQL integration tests for concurrent final-manager removal;
- frontend tests for exact role option consumption, candidate query shaping,
  add/remove retry and error rendering; and
- a real browser acceptance test reached by `npm run test:browser:real` using
  PostgreSQL, FastAPI and React.

No migration is expected. If the implementation discovers a required schema
change, stop implementation and reopen this Gate.

## Out of scope

M5.3 does not include administrator pages, credential reset, email recovery,
custom Scenario authoring, new Scenario versions, notifications, deployment,
or production-scale team directory features.

