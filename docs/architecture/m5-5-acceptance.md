# M5.5 Controlled Pilot Hardening Acceptance

## Clean initialization

On a fresh PostgreSQL service after the repository's clean migration command:

1. bootstrap the first organization and system administrator through the
   existing bootstrap path;
2. publish exactly `process_review@1` and `compliance_review@1` through the
   exact publication path;
3. verify duplicate publication and an unknown exact version fail safely; and
4. verify the administrator status shows both exact versions as ready because
   the organization publication and exact code registry are present.

The fixture must not pre-create the target administrator or silently bypass the
bootstrap/publication path. Any supporting fixture data must belong to a
separate, clearly named test organization or be created through the same
application service used by the product.

## Administrator and first login

Through the real administrator page:

1. create and edit a department;
2. create at least two ordinary users and assign their primary department;
3. log in as one new user with the initial password;
4. complete the existing forced password-change flow; and
5. verify the changed-password session reaches the permitted business page.

No temporary or initial password may be written to browser storage, URLs,
response bodies beyond the submitted request, audit metadata or test logs.

## Two exact plan-first cases

The first user creates both supported cases through the React plan-first flow.
For each case, acceptance verifies:

- a `ReviewPlan` is created before the `ReviewCase`;
- the returned `plan_id` is the ID sent to the Case request;
- `process_review@1` sends exactly `area_code` and `review_type`;
- `compliance_review@1` sends exactly `standard_reference` and
  `scope_summary`;
- invalid scenario data receives a safe validation response; and
- refresh/re-entry restores the exact plan by ID.

During one Case creation, the network request fails after the plan response.
The retry succeeds with exactly one plan POST and two Case POST attempts. No
title matching or duplicate plan is allowed.

## Team management and collaboration access

Using the existing Case team surface:

1. an authorized manager searches and adds a same-organization active ordinary
   user using an exact Scenario role;
2. the member is visible with the exact role label;
3. the member is removed and the corresponding activity is visible;
4. an attempt to remove the last effective manager returns the established
   conflict and leaves membership and activity unchanged; and
5. another allowed team member can use the existing collaboration page.

An ordinary user without `manage_case_members` receives a safe 403 and no
candidate names. Invalid roles receive a validation response and no names.

## Organization isolation

The real API and browser journey must verify all of the following:

- a user cannot read or mutate a foreign organization plan or case;
- a foreign organization is absent from the review catalog;
- a foreign user is absent from Case member candidates;
- an administrator cannot read or mutate foreign departments/users/status;
- inactive users do not appear in candidates or gain business access; and
- a platform `system_admin` without an explicit Case role cannot bypass Case
  business authorization.

The test must assert both safe HTTP results and absence of foreign display names
from the rendered page.

## Credential recovery

An administrator resets a same-organization user's credential with a policy-
compliant temporary password. Acceptance verifies:

- the response is the existing safe User response with no credential fields;
- the old user session is revoked;
- the old password no longer authenticates;
- the next login with the temporary password enters forced password change;
- the new password completes the existing flow; and
- one reset audit event plus expected session-revocation events exist without
  the temporary password or its hash.

An invalid short password, missing target and cross-organization target must
leave credential, session and audit state unchanged and must not echo secrets.

## Required automated evidence

The slice must include:

- focused API/integration assertions for cross-slice isolation, exact version
  behavior, failed Case retry semantics, member revocation and credential
  recovery;
- a real browser test and deterministic seed registered in
  `npm run test:browser:real`;
- full backend checks, including architecture, OpenAPI, migrations and
  PostgreSQL tests;
- frontend typecheck, lint, unit tests and build;
- real browser acceptance against PostgreSQL, FastAPI and React; and
- a Review Bundle tied to the fixed candidate and exact-head GitHub run.

## Go / No-Go

Go only if all conditions hold:

- no unresolved P1 or P2;
- both exact scenarios are created in the real browser journey;
- members can be added and revoked safely;
- no cross-organization catalog, candidate or administrator data leaks;
- clean migration plus bootstrap/publication succeeds;
- administrator credential recovery is safe and forces password change;
- the real browser test runs through the canonical CI command;
- exact-head GitHub Actions is green;
- Review Bundle is complete and current; and
- known limitations and rollback boundaries are recorded in the final review.

No-Go if any required journey depends on a hidden fixture shortcut, a stale
working tree, a non-exact candidate head, a skipped PostgreSQL/browser job, a
new unreviewed architecture, or an unresolved P1/P2.

## Known controlled-pilot limitations

The pilot still accepts the previously documented plan-request network
ambiguity: if the server commits a plan but the client receives no response,
the UI does not guess or search by title. Strong idempotency is a future
architecture slice. Production deployment, email recovery, MFA, SSO, custom
Scenario authoring, evidence storage, dashboards and scheduling remain M6 or
later concerns.
