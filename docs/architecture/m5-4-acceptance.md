# M5.4 Minimal Pilot Administration Acceptance

## Authorization and isolation

- No session, expired/revoked session, inactive user, ordinary user or
  cross-organization target can read or mutate administrator data.
- An active `system_admin` can read only its own organization's organization,
  departments, users and Scenario catalog.
- A system administrator's platform role does not grant Case or Scenario
  business access.
- Missing and cross-organization target IDs produce safe not-found/conflict
  responses without a partial mutation.

## Departments

Using the real API and administrator page, an administrator can:

1. list all departments in deterministic server order;
2. create a department with an optional same-organization parent;
3. rename a department and change its parent through the existing patch;
4. enable or disable a department; and
5. see a clear validation/conflict response while retaining the last valid
   server state.

Cross-organization parents and invalid hierarchy changes are rejected by the
backend. No client-side hierarchy inference is treated as authorization.

## Users

Using the real API and administrator page, an administrator can:

1. list users in its organization;
2. create an ordinary user with a valid initial password;
3. assign or clear the user's primary department within the organization;
4. edit the display name and existing platform role;
5. enable or disable the user; and
6. observe the existing last-active-system-admin protection.

The page uses the returned user and department IDs, does not update a foreign
organization, and does not invent a new platform role.

## Credential reset and first-login recovery

For a target user with a local credential:

1. an administrator submits a policy-compliant temporary password;
2. the request succeeds without returning or echoing that password;
3. the target credential has a new password hash and
   `must_change_password = true`;
4. all target active sessions are revoked;
5. one `admin.user_credential_reset` event and the expected session-revocation
   events are persisted; and
6. the target can log in with the temporary password and is routed through the
   existing forced password-change page before business access.

The old password and all old sessions stop working. A short password is
rejected without changing the credential, sessions or audit state. A missing
credential returns a clear conflict. The temporary password, its hash and any
credential secret are absent from response bodies, audit metadata, URLs and
logs.

## Scenario installation status

The administrator page reads the existing Scenario list and exact version
endpoints and displays:

- each installed organization Scenario key and display name;
- its active/inactive state; and
- every exact published version as `key@version` with its publication time.

It must not offer a runtime publish/editor action, substitute `latest`, merge
versions by key, or display a version not returned by the server.

## Browser journey

The real acceptance test uses PostgreSQL, FastAPI and the React page to prove:

1. bootstrap an organization and first system administrator;
2. log in as administrator and open `/admin`;
3. create and edit a department;
4. create a user with an initial password and assign its department;
5. log in as that user, complete the existing forced password change, and verify
   business access is then available;
6. return as administrator, edit the user and disable/re-enable it;
7. reset the user's credential and verify the prior session is rejected and the
   forced password-change flow is required on the next login; and
8. verify exact Scenario installation/version status is visible.

A separate API/integration path verifies an ordinary user, cross-organization
IDs, invalid password, missing credential and last-system-admin protection.

## Required verification

The slice must include:

- API/OpenAPI coverage for every existing admin route used by the page and the
  credential-reset request/response;
- integration coverage for authorization, organization isolation, department
  and user mutations, credential hashing, `must_change_password`, session
  revocation, audit events and atomic failure;
- regression coverage proving the temporary password and hash are never
  returned or persisted in audit metadata;
- frontend tests for CRUD request shaping, exact IDs, scenario-version display,
  reset-success/error handling and safe error rendering;
- a real browser test registered in `npm run test:browser:real`; and
- `check_architecture.py`, `check_openapi.py`, full pytest, frontend typecheck,
  lint, unit tests and exact-head GitHub Actions evidence.

No migration is expected. A required schema migration reopens this Gate.

## Out of scope

M5.4 does not include organization creation UI, multi-organization switching,
email password recovery, MFA, SSO, custom Scenario authoring, publishing UI,
third-party identity providers, evidence, dashboards, deployment or M5.5 final
pilot evidence.
