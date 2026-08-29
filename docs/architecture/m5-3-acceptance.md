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

An active same-organization system administrator is absent from candidates.
This does not change the existing add contract: an authorized Case manager may
explicitly add that account with an exact valid Case role, and the account's
Case role—not its platform role—then supplies Case business authority.

## Add and remove

- Both `process_review@1` and `compliance_review@1` accept the exact Case role
  keys `lead`, `auditor`, `reviewer` and `observer`.
- An invalid role is rejected by the backend even if a client sends it
  directly.
- The existing add endpoint remains the only add mutation for this slice.
- A valid DELETE removes only the requested `(case_id, user_id, role_key)`.
- The delete response identifies the removed membership.
- A successful delete creates exactly one `review_case.member_removed` Activity
  whose metadata identifies the target user and role. The Case detail UI
  refreshes both the member list and Activity after the mutation.
- A missing membership, unauthorized actor or cross-organization target does
  not remove anything or create an Activity.

## Last-manager invariant

The creator's `lead` membership is initially present. With one effective active
manager remaining, deleting that manager's `lead` returns HTTP 409 and leaves
both the membership and Activity count unchanged. A sole manager holding both
`lead` and `observer` may delete `observer`, because the complete remaining
role set still grants management; deleting `lead` then returns 409. If another
effective manager exists, deleting one manager succeeds. Effective managers
are unique active User IDs evaluated through the exact Scenario authorization
policy, not membership rows. An inactive account holding a manager role does
not count as an effective actor for this protection.

Two concurrent transactions attempting to remove the final two effective
managers must serialize on the Case row lock, re-read memberships and actor
authorization after lock acquisition, and leave at least one effective manager.
The second result may be HTTP 409 when its actor remains authorized but its
delete would remove the final manager, or HTTP 403 when the earlier committed
delete removed its management authority. In either case the rejected
transaction creates no partial Activity. A deterministic ordering test must
prove the explicit final-manager 409, and a genuine two-session race must
assert the safety invariant rather than one universal status code.

All four effective-manager-changing operations—Case creation, member add,
member removal and User deactivation—must acquire the same Organization row
lock before enumerating or changing manager relationships. They then use the
deterministic Case-ID and User-ID lock order before exact-policy evaluation.
This prevents an add/create operation from appearing after deactivation has
enumerated affected Cases.

A concurrent add-vs-deactivate, create-vs-deactivate and remove-vs-deactivate
PostgreSQL test must prove that no committed ordering produces zero active
effective managers. A deactivation that would violate the invariant returns
HTTP 409 through the existing admin user PATCH path and atomically preserves:
the User's active state, its existing sessions, the absence of an
`admin.user_updated` PlatformAuditEvent, and all Case memberships/Activities.

The cross-domain coordinator owns this check. `PlatformAdministrationService`
must remain unaware of ReviewCase and Scenario business concepts.

## Frontend journey

Using a real authenticated React page:

1. open a visible Case detail page;
2. read the exact Case role definitions from the exact adapter;
3. search candidates for `lead`, `auditor`, `reviewer` and `observer` without
   exposing server-side names before authorization;
4. add one candidate and observe the member list refresh;
5. remove that membership and observe the list and Activity refresh;
6. attempt to remove the final manager and display the conflict while keeping
   the manager visible;
7. observe member and Activity refresh after successful add/remove; and
8. verify a non-manager sees a safe permission error and no candidate names.

## Required verification

The slice must include:

- API/OpenAPI contract tests for candidate response and DELETE parameters;
- service/repository tests for exact role validation, organization/active-user
  filtering, permission-before-name ordering, atomic Activity behavior and
  last-manager protection;
- PostgreSQL integration tests for multi-role post-delete evaluation,
  concurrent final-manager removal, and removal versus manager deactivation;
- PostgreSQL/API concurrency tests for add-vs-deactivate and
  create-vs-deactivate using the shared Organization lock;
- atomic failed-deactivation assertions covering User state, sessions and
  PlatformAudit;
- regression coverage for explicit system-admin Case membership semantics;
- `openapi/openapi.json` updates and API contract checks for the new GET and
  DELETE operations;
- frontend tests for exact role option consumption, candidate query shaping,
  add/remove retry and error rendering; and
- a real browser acceptance test reached by `npm run test:browser:real` using
  PostgreSQL, FastAPI and React.

The canonical CI command must include the M5.3 browser specification through
`web/package.json`; no workflow change is required.

No migration is expected. If the implementation discovers a required schema
change, stop implementation and reopen this Gate.

## Out of scope

M5.3 does not include administrator pages, credential reset, email recovery,
custom Scenario authoring, new Scenario versions, notifications, deployment,
or production-scale team directory features.
