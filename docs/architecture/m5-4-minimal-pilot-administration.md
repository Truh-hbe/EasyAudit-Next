# M5.4 Minimal Pilot Administration

## Gate status

This document is the independently executable M5.4 Architecture / Acceptance
Gate. It is governed by the M5 parent charter and authorizes only the minimum
administrator surface required to configure a controlled pilot. M5.5 remains
out of scope until its own Gate passes.

## Goal

Replace the administrator placeholder page with a usable, organization-scoped
administration surface for departments, users, credentials and installed
Scenario status. The backend remains the only authorization and validation
authority, and the existing platform administration service remains the owner
of platform facts and mutations.

## Existing semantics to preserve

- Only an authenticated active `system_admin` may call `/api/v1/admin/*`.
- Organization boundaries are enforced by the backend for every target ID.
- A `system_admin` platform role is not a shortcut for any ReviewCase or
  Scenario business permission.
- The existing last-active-system-admin protection remains in force.
- The existing local password policy remains authoritative: a local password
  has at least 12 characters.
- A `must_change_password` identity is allowed to reach the credential
  remediation flow and is blocked from business APIs until it completes the
  existing `/api/v1/me/password` flow.
- Scenario state is read from the existing organization catalog, exact
  published versions and the exact code registry. The administrator page must
  not create, edit or infer Scenario definitions.

## Backend contract

The existing contracts remain the source of truth for:

```text
GET   /api/v1/admin/organization
GET   /api/v1/admin/departments
POST  /api/v1/admin/departments
PATCH /api/v1/admin/departments/{department_id}
GET   /api/v1/admin/users
POST  /api/v1/admin/users
GET   /api/v1/admin/users/{user_id}
PATCH /api/v1/admin/users/{user_id}
GET   /api/v1/admin/scenarios
GET   /api/v1/admin/scenarios/{key}/versions
GET   /api/v1/admin/scenario-status
```

The existing Scenario reads remain available for their existing consumers. The
administrator page must use the new aggregate status projection rather than
reconstructing readiness from separate responses. Its response is:

```json
{
  "items": [
    {
      "scenario_key": "process_review",
      "display_name": "Process Review",
      "is_active": true,
      "versions": [
        {
          "scenario_version": 1,
          "published_at": "2026-08-30T00:00:00Z",
          "registry_present": true,
          "ready": true
        }
      ]
    }
  ]
}
```

The server computes `registry_present` with an exact
`ScenarioRegistry.get(scenario_key, scenario_version)` lookup. `ready` is true
only when the organization Scenario is active, that exact version is
published, and the exact code registry entry exists. A persisted publication
without its exact registry entry remains visible but is `ready: false`; it may
not be presented as installed or healthy. No `latest`, nearby-version,
key-only or frontend fallback is allowed. The projection includes inactive
Scenarios so stale state is visible, but inactive versions are not ready.

The UI must display each exact `scenario_key@version` returned by this server
projection and may not use client-created versions or a generic Scenario
editor.

Add the following endpoint:

```text
POST /api/v1/admin/users/{user_id}/credential-reset
```

Request:

```json
{
  "temporary_password": "at-least-12-characters"
}
```

The successful response is HTTP 200 with the existing `UserResponse` for the
target user. The response contains no credential, session token or password
field. A missing or cross-organization target returns HTTP 404 without
revealing whether another organization contains it; a target without a local
credential returns HTTP 409; a valid request for either an active or inactive
same-organization user is allowed. An ordinary authenticated user receives
HTTP 403 before target data is loaded, and an unauthenticated request receives
HTTP 401.

The request model treats `temporary_password` as an opaque string and the
service applies the authoritative local password policy. Policy failure is a
safe HTTP 422 response with a generic message; validation responses, logs and
audit metadata must not echo the submitted password or its hash.

The endpoint must:

1. require the existing `system_admin` dependency before loading target data;
2. reject a missing or cross-organization target without mutation;
3. validate the temporary password with the existing local password policy;
4. lock and replace the target local credential's password hash;
5. set `must_change_password = true` and update the password-change timestamp;
6. revoke every active session belonging to the target user, using the existing
   session-revocation and audit path;
7. append exactly one `admin.user_credential_reset` PlatformAudit event for the
   reset operation; and
8. commit all credential, session and audit changes as one request transaction.

The target credential row lock is the serialization point shared with the
existing login and password-change flows. The implementation must reuse that
lock/update path and the existing session-revocation service, so reset versus
login and reset versus password-change have deterministic safe outcomes.

The response must be the frozen `UserResponse` contract above and must never
return the temporary password or password hash or place either in audit
metadata, logs or error text. A caller with an ordinary platform role receives
403 and no target data is loaded.

The existing department and user mutations remain the only mutations for those
resources. No delete endpoint, bulk operation, email recovery, MFA, SSO or
unrelated authorization change is introduced by this Gate.

## Frontend surface

Replace the `/admin/*` placeholder in `ProductShell` with a protected
administrator page. The page must use server responses and support:

- loading the organization and showing its current status;
- listing, creating, editing and enabling/disabling departments;
- listing, creating and editing users, including primary department, platform
  role and active status;
- starting a credential reset for a selected user with a temporary password;
- showing a safe reset-success acknowledgement without echoing the password;
- listing installed Scenario definitions and their exact published versions and
  active state; and
- clear 401/403/404/409/422 feedback with retry while preserving the current
  server-backed state.

The page must not grant access based only on a client-side role check. The
navigation hint may be role-aware, but every data load and mutation must rely
on the backend response. An ordinary user visiting `/admin` must see the
existing server 403 behavior and no administrator data.

The page must not expose password fields after submission, persist temporary
passwords in browser storage, or place them in URLs. It must use exact IDs from
server responses for department/user updates and exact Scenario versions for
status display.

## Persistence and architecture boundary

- No database migration is authorized by this Gate. If implementation discovers
  that an existing table cannot express the required operation, stop and reopen
  architecture review.
- Keep `PlatformAdministrationService` as the owner of department/user,
  credential, session and PlatformAudit mutations. Do not move ReviewCase or
  Scenario business rules into it.
- The existing admin user update path must continue to delegate through the
  M5.3 `CaseTeamUserCoordinator.update_user` orchestration before it reaches
  `PlatformAdministrationService`, preserving the final-effective-case-manager
  invariant. M5.4 must not bypass, duplicate or weaken that coordinator and
  must not add Review imports to `PlatformAdministrationService`.
- The credential reset may reuse the existing `AuthenticationService` session
  revocation path and `LocalCredentialRepository`; no general account-recovery
  subsystem is authorized.
- The Scenario status panel is a read projection over the existing catalog and
  code-defined exact registry. It must not persist a second Scenario truth.

## Scope

Implementation is limited to:

- this Gate and its acceptance document;
- `.easyaudit/development-state.json`;
- existing admin API contracts/router and the platform administration service
  needed for credential reset;
- the existing platform repositories only if the atomic reset needs a narrow
  lock/read capability;
- `openapi/openapi.json`;
- the administrator API client, `/admin` page, its focused tests and the
  existing `ProductShell` route replacement;
- M5.4 API/integration tests and the real browser acceptance seed/spec; and
- the existing canonical frontend command registration if required for that
  browser spec.

The following remain forbidden: `alembic/**`, `.github/workflows/**`,
`web/src/app/auth/**`, `web/src/app/router/**`, Review business semantics,
notifications, workbench, evidence storage, dashboard redesign, generic
Scenario builders, deployment, production scheduling, email recovery, MFA,
SSO and a large design-system rewrite. The only `web/src/app/**` file in this
Gate is the explicitly allowed `web/src/app/shell/ProductShell.tsx` route
replacement.

## Gate lifecycle

```text
GATE_DRAFT -> GATE_REVIEW -> IMPLEMENTATION -> FINAL_REVIEW
-> MERGE_AUTHORIZED -> MERGED
```

This Gate authorizes no M5.5 implementation. Every phase transition requires
the outer state file, an independent Codex with ChatGPT review and the
repository's exact-head evidence.
