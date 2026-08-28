# M3.5.1 — Product Shell, Authentication & Navigation Implementation Gate

M3.5.1 is the first executable Product Surface slice under the approved M3.5 architecture.

Baseline:

```text
main@b1bf32cd86b7adbb28220c502f8af7c9762fa667
```

That baseline is the merge commit of the approved M3.5 Architecture Gate fixed at:

```text
d19c897468fe1c179c939a59b8fd38f69c7c87c1
CI #224 — success
```

This document is an **Implementation Gate only**. The Gate PR remains documentation-only until accepted. It must not yet add React source, `package.json`, Vite configuration, Node tooling, frontend CI, CORS middleware, CSRF implementation, backend authentication changes, static-file serving, reverse-proxy configuration, migrations, or new APIs.

Executable M3.5.1 frontend work begins only after this Gate is explicitly accepted **and** the separately reviewed credential-readiness backend prerequisite described below has been accepted and merged.

## Goal

M3.5.1 establishes the minimum long-lived browser application foundation required by later M3.5 slices:

```text
browser shell
+ existing server Session authentication
+ server-owned credential readiness
+ protected-route resolution
+ primary navigation
+ same-origin API client boundary
+ safe logout/session-expiry behavior
+ empty/placeholder product routes for later slices
```

It does **not** implement Workbench business content, ReviewCase details, Finding/Action collaboration, Notification Center, Management projections, or Reminder actions. Those remain M3.5.2–M3.5.4.

The M3.5.1 invariant is:

> **The browser may know whether it currently has an authenticated server Session and may present a server-returned credential requirement, but it does not acquire a second authentication authority, credential authority, business authorization model, or domain cache.**

## Existing authentication contract and the credential-readiness prerequisite

M3.5.1 continues to consume the already-merged M1 Session endpoints and cookie behavior:

```text
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/me
```

Existing cookie contract:

```text
__Host-easyaudit_session
Secure
HttpOnly
SameSite=Strict
Path=/
```

However, those three endpoints are **not by themselves sufficient for the complete Product Surface authentication journey** because the merged Platform Core already contains a distinct server-owned credential posture:

```text
LocalCredential.must_change_password
```

Normal administrator-created local users default to:

```text
must_change_password = true
```

A valid Session is intentionally allowed to exist while this requirement remains true. The current backend business dependency then enforces:

```text
authenticated Session
+ must_change_password = true
        ↓
BusinessIdentity
        ↓
403 Password change required before business APIs
```

Therefore M3.5.1 must not collapse these two facts into one:

```text
server Session is valid
≠
server says credential is ready for business access
```

The Product Surface must not guess credential readiness from a 403, from user role, from route history, or from frontend-only state.

Before React implementation starts, a separate narrow **M3.5.1 Credential Readiness Backend Prerequisite Gate** must define and implement the server contract for:

```text
1. exposing the current authenticated user's credential requirement
2. allowing the current authenticated user to satisfy a required password change
3. defining current/other Session behavior after password change
4. clearing must_change_password atomically with the credential update
5. preserving append-only platform audit semantics
```

Exact API spelling belongs to that backend prerequisite Gate, not to React code. M3.5.1 may consume the reviewed result after it is merged; it may not invent an alternate frontend contract.

The Product Surface must not require a browser-readable access token, refresh token, JWT, bearer token, or frontend session secret.

`LoginResponse.session_id` remains metadata, not a bearer credential. The browser application must not treat it as an authentication token or persist it as one.

## Browser-visible same-origin contract

The approved M3.5 architecture freezes browser-visible same-origin behavior:

```text
https://easyaudit.example/
├── /          Product Surface
└── /api/v1/*  FastAPI API
```

M3.5.1 implementation must preserve this contract.

The application API client uses relative URLs such as:

```text
/api/v1/me
/api/v1/auth/login
/api/v1/auth/logout
```

Any credential-readiness endpoint accepted by the prerequisite Gate must use the same relative `/api/v1/*` browser contract.

The implementation must not embed a separate production API origin into feature code or introduce a credentialed cross-origin browser security model merely for development convenience.

Forbidden M3.5.1 fixes include:

```text
allow_origins=["*"] for session traffic
credentials-enabled cross-origin API design
SameSite relaxation
Secure=False cookie variants for the Product Surface
copying a server Session token into JavaScript-readable storage
new frontend JWT issuance
```

A future separate UI/API browser-origin deployment remains subject to a separate Authentication / Browser Security Architecture Gate.

## Development transport

Development must emulate the same browser-visible contract rather than changing application semantics.

Preferred topology:

```text
Browser
  │ HTTPS
  ▼
Vite development origin
  ├── /                React dev assets/routes
  └── /api/v1/*        proxy
                         ↓ internal development transport
                       FastAPI
```

The browser must see one origin for Product Surface and `/api/v1/*`.

Because the existing cookie is always `Secure`, M3.5.1 must not weaken the cookie for local development. The implementation must provide a development/browser-test setup in which the unchanged Secure cookie can actually be accepted and sent. An HTTPS Vite/browser origin is the preferred explicit solution.

A browser-specific localhost exception must not become the architecture contract.

Internal proxy transport from Vite to local FastAPI may use HTTP because it is not the browser trust boundary.

## Production route ownership

M3.5.1 must keep browser route ownership unambiguous.

At the external origin:

```text
/api/v1/*
→ backend API only

Product Surface routes
→ SPA entry point
```

The backend operational `/health` endpoint is not a Product Surface API and must not be consumed by normal React authentication/navigation logic.

Future reverse-proxy/static-hosting implementation must ensure API routes never fall through to the SPA and SPA routes never shadow `/api/v1/*`.

The exact production proxy product is not frozen here.

## Frontend source boundary

Executable implementation, once approved and unblocked by the backend prerequisite, should create one top-level frontend workspace:

```text
web/
```

M3.5.1 should not mix React source into the Python package under `src/easyaudit_next/`.

Conceptual structure:

```text
web/
├── src/
│   ├── app/
│   │   ├── router
│   │   ├── auth
│   │   └── shell
│   ├── api/
│   ├── features/
│   └── main
├── public/
├── package.json
├── tsconfig*.json
└── vite.config.*
```

Exact filenames may vary, but the boundaries must remain recognizable.

## Initial frontend technology boundary

M3.5.1 implementation may introduce the minimum browser stack needed for this slice:

```text
React
TypeScript
Vite
React Router or equivalent declarative client router
frontend unit/component test tooling
browser-level acceptance tooling where needed
```

The lockfile is committed and package installation in CI must be deterministic.

This Gate does not require Redux, a global domain store, a design-system framework, a chart library, WebSocket client, offline cache, service worker, or a generic form engine.

A server-state/query library is not required merely to implement authentication. If introduced, it must remain a cache of server truth and must support complete protected-cache clearing on logout/session expiry. The choice does not become a business-state authority.

## Authentication state model

The browser application may own only a small **Session-resolution state**, not a second Session domain.

Minimum Session states remain:

```text
resolving
anonymous
authenticated(current user metadata)
```

Credential readiness is an **orthogonal server-returned requirement attached to an authenticated user**, not a fourth Session lifecycle state and not a frontend authority.

Conceptually:

```text
authenticated
    │
    ├── credential ready
    │      → normal Product Surface shell/routes
    │
    └── server requires password change
           → credential remediation UX
           → business APIs remain server-blocked
```

The frontend may represent this requirement for rendering, but only from the reviewed server contract. It cannot set, clear, infer, or bypass it locally.

On cold start for a protected route after the backend prerequisite exists:

```text
app starts
→ auth = resolving
→ current-user server resolution
   ├── no valid Session → 401 → anonymous
   └── valid Session → authenticated + server credential requirement
```

Protected content must not render before Session resolution finishes.

Normal business placeholders/surfaces must not be presented as available when the server says password change is required. The user must instead reach the credential-remediation route/UX supplied by this slice.

The browser must not decide an existing Session is valid merely because cached user metadata exists. A page reload therefore re-enters server current-user validation.

## Login behavior

The login page submits credentials only to the existing:

```text
POST /api/v1/auth/login
```

The browser receives the server-managed HttpOnly cookie through the normal same-origin response. React does not read the cookie value and does not need to know it.

A successful login proves only that a valid server Session was established. It does **not** prove credential readiness.

After successful login, the Product Surface must consume the reviewed server credential-posture contract before deciding whether to enter normal product routes:

```text
POST login → 200
→ authenticated Session exists
→ resolve server credential requirement
   ├── ready
   │    → safe intended route or /me/workbench
   └── password change required
        → credential remediation UX
        → do not bypass BusinessIdentity
```

On invalid credentials:

```text
401
→ remain anonymous
→ show non-sensitive login error
→ do not create local auth state
```

Credentials must not be persisted in localStorage/sessionStorage.

## Current-user identity and credential-posture boundary

The server current-user contract remains the browser bootstrap source for current identity. The separately reviewed prerequisite must additionally expose the current authenticated user's credential requirement in a server-owned form.

The UI may use returned platform metadata such as display name and `platform_role` for presentation/navigation hints, and may use returned credential posture only to route the authenticated user to server-required remediation.

Important distinctions:

```text
platform_role
→ may influence platform-admin navigation presentation

platform_role
≠ ReviewCase/Finding/Action business authorization

credential requirement
→ server-owned security posture for authenticated user

credential requirement
≠ frontend permission flag
```

M3.5.1 must not convert `system_admin` into a global business permission shortcut and must not allow a local UI flag to clear `must_change_password`.

## Credential remediation UX boundary

M3.5.1 may implement the minimal browser UX necessary to satisfy the reviewed backend password-change requirement because that is part of making the first authenticated Product Surface usable for normally provisioned users.

This UX may:

```text
show that password change is required
collect the inputs required by the reviewed backend command
submit only to that backend command
show validation/server errors safely
re-resolve current-user credential posture after success
continue to normal Product Surface only after server reports ready
```

It must not:

```text
clear must_change_password locally
pretend a successful local form means business access is enabled
bypass BusinessIdentity
change another user's credential
invent password policy independently of the backend
store current/new password in browser storage
```

The exact endpoint and password-change transaction semantics are prerequisites owned by the backend Gate.

## Logout behavior

Normal logout uses only:

```text
POST /api/v1/auth/logout
```

On confirmed success:

```text
server revokes Session
→ server clears cookie through existing contract
→ frontend clears all protected in-memory/client caches
→ auth state becomes anonymous
→ navigate to /login
```

If the server reports that the Session is already invalid/expired, the frontend still clears protected client state and moves to anonymous UX.

A network/server failure must not be represented as confirmed server-side revocation. Protected client data should still be removed from the visible UI for confidentiality, while the failure is handled explicitly rather than inventing a local token revocation mechanism.

## Global 401/session-expiry behavior

For authenticated Product Surface requests, a server 401 means the browser must stop treating the current Session as authenticated.

M3.5.1 must provide one centralized path equivalent to:

```text
401 from protected API
→ clear protected client state
→ auth = anonymous
→ navigate/show safe login UX
```

This must not expose stale protected page content behind a login overlay.

Login's own expected `401 Invalid credentials` is handled as login failure, not as an authenticated-session-expiry event.

A server 403 whose reviewed meaning is `Password change required before business APIs` is **not** Session expiry and must not be converted into anonymous state. Under the final design, normal Product Surface routing should already know the server credential requirement before attempting business surfaces; a 403 remains a server-authoritative backstop, not the primary discovery mechanism.

## Shared API client boundary

M3.5.1 establishes one reusable transport boundary for later slices.

Responsibilities:

```text
same-origin relative request URLs
JSON request/response handling
standard error object containing HTTP status + safe detail
401 signaling to auth/session layer
server credential-requirement response handling without inventing authority
AbortSignal/request cancellation support where practical
no embedded business authorization logic
```

Feature modules must not scatter direct production `fetch()` implementations with inconsistent auth/error semantics.

The API client must not:

```text
read/write the HttpOnly cookie
attach a custom bearer token
clear must_change_password locally
select reminder recipients
infer workflow permission
infer lifecycle transition legality
recompute overdue truth
```

M3.5.1 only needs typed transport contracts for authentication/current-user/credential-remediation APIs actually accepted for this slice. Broader OpenAPI client generation may be added incrementally in later slices, but handwritten DTOs must remain wire representations.

## Product shell

The authenticated shell establishes stable global chrome only:

```text
application identity/header
primary navigation
current user display
logout action
main route outlet
loading/error/session-expiry states
credential-remediation state when server requires it
```

It must not become a dashboard domain.

Primary areas remain the approved M3.5 information architecture:

```text
我的工作
审查活动
通知
管理视图
管理设置
```

Default credential-ready authenticated landing route:

```text
/me/workbench
```

An authenticated user whose server credential requirement is unresolved or requires password change must not be treated as credential-ready merely because the shell knows their user identity.

## Navigation and slice boundaries

M3.5.1 may create route placeholders for later Product Surface slices so the shell and route tree are stable.

Conceptual routes:

```text
/login
credential-remediation route chosen by implementation

/me/workbench
/me/notifications
/review-cases
/management
/admin
```

M3.5.1 route placeholders must be explicit product placeholders, not fake business implementations.

For example, until M3.5.2 implements Workbench:

```text
/me/workbench
→ credential-ready authenticated shell + explicit "Workbench surface arrives in M3.5.2" state
```

It must not query Cases/Findings/Actions and synthesize a temporary Workbench.

Likewise Notification/Management placeholders must not fabricate data or duplicate future read-side logic.

## Management settings navigation

`管理设置` maps to platform administration, not business management authorization.

The shell may hide/disable the `/admin` navigation item for a returned non-`system_admin` user as a UX hint because platform administration is governed by the existing platform role.

However:

```text
hidden admin nav
≠ backend authorization
```

Direct requests to `/api/v1/admin/*` remain server-authoritative.

No platform role may be reused to grant ReviewCase/Finding/Action access.

## Protected-route behavior

Protected routes must follow this ordering:

```text
route entered
→ resolve current server Session + reviewed credential requirement
→ no Session: /login
→ authenticated + password change required: credential remediation UX
→ authenticated + credential ready: render normal shell/route
```

The application must avoid:

```text
render protected business placeholder/page
→ later discover password-change 403
→ redirect remediation
```

as well as:

```text
render protected data
→ later discover 401
→ flash hidden content
```

A remembered intended destination may be used after successful login and credential remediation, but it must be an internal Product Surface path, not an arbitrary external redirect target.

Open-redirect behavior is forbidden.

## `/login` behavior for an existing valid Session

Visiting `/login` while a valid server Session already exists should not create a second login authority.

The route must resolve the server current-user/credential posture. A credential-ready user may be redirected to `/me/workbench` or another safe internal destination. A user who still requires password change must be routed to credential remediation rather than misleadingly treated as a normal credential-ready user.

The browser must not decide this solely from stale local user data.

## Client storage boundary

M3.5.1 may use browser storage only for non-sensitive presentation preferences if needed.

It must not store:

```text
session cookie value
auth token
JWT
password
raw login credentials
server Session secret
client-owned must_change_password override
business authorization snapshot used as authority
```

Authentication and credential readiness must be reconstructible from the server after reload.

## Cache-clearing boundary

M3.5.1 must establish a single conceptual operation for removing protected browser data when authentication ends.

It must clear at least:

```text
current-user cached data
credential-posture cache
protected route data owned by the current runtime
future registered server-query caches
sensitive transient state that should not cross users
```

The mechanism may evolve as later slices add query caches, but logout/session expiry must have one reliable clearing boundary rather than feature-by-feature cleanup.

Credential-remediation form secrets such as current/new password must be transient and must be discarded after submit/navigation/error handling as appropriate; they must never cross users through a cache.

## Backend credential prerequisite — mandatory before React implementation

The previous Gate assumption that `POST login`, `POST logout`, and `GET /api/v1/me` alone are sufficient for the complete shell authentication journey is withdrawn.

The merged backend currently supports a valid Session while `must_change_password=true`, and BusinessIdentity blocks business APIs with 403. M3.5.1 therefore has a real backend prerequisite, not a frontend convenience request.

The separately reviewed prerequisite must establish a server-owned path for:

```text
current-user credential posture
+ authenticated self-service password change
+ atomic password hash/password_changed_at/must_change_password update
+ reviewed current/other Session semantics
+ platform audit facts
```

M3.5.1 frontend implementation remains blocked until that prerequisite Gate passes and its executable backend implementation is merged.

The frontend PR itself must not opportunistically add or alter backend endpoints. If any additional backend need appears after the prerequisite is merged, implementation stops and returns to a backend Gate again.

The prerequisite must not introduce:

```text
browser-readable Session tokens
frontend JWTs
BusinessIdentity bypass
admin-only clearing of a user's requirement as a substitute for self-service remediation
cross-origin auth transport
```

## No CORS/CSRF scope expansion

Because M3.5.1 uses the approved same-origin browser contract, it must not add broad CORS middleware or redesign CSRF policy as speculative infrastructure.

The absence of cross-origin Product Surface traffic is intentional.

If implementation discovers that a new browser-origin relationship is actually required, M3.5.1 pauses and re-enters the Authentication / Browser Security Architecture Gate defined by M3.5.

## CI boundary for executable implementation

Once this Gate and the backend prerequisite are approved and executable frontend work starts, CI must preserve all existing backend checks and add deterministic frontend checks.

At minimum the implementation fixed head should run:

```text
existing Python/PostgreSQL CI unchanged
+ frontend dependency install from lockfile
+ TypeScript typecheck
+ frontend lint/static checks
+ unit/component tests
+ production frontend build
```

At least one browser-level acceptance test is required for the real authentication loop because HttpOnly/Secure cookie behavior and the credential-remediation journey cannot be proven by component tests alone.

A browser framework such as Playwright is acceptable. Exact tooling is an implementation choice, but acceptance must exercise a real browser cookie jar against the actual FastAPI + PostgreSQL authentication/credential contract.

## Browser acceptance environment

Browser acceptance must prove the unchanged cookie contract under a browser-visible secure same-origin setup.

Conceptually:

```text
Browser HTTPS origin
├── React
└── /api/v1/* proxy → FastAPI
                         ↓
                    PostgreSQL
```

Tests must not replace the real cookie with a fake localStorage token or stub the entire authentication/credential boundary.

Component tests may mock APIs for presentation behavior, but fixed-head authentication proof must include the actual backend login/session/current-user/password-change/logout path required by the final reviewed contracts.

## Error handling in this slice

M3.5.1 must provide understandable UX for:

```text
invalid credentials
password change required
password-change validation/current-password failure
session expired
backend unavailable
unexpected login/logout/password-change failure
unknown frontend route
```

Error handling must not leak password values or auth secrets.

## Accessibility minimum for shell/auth

This first slice already participates in the final M3.5 accessibility contract.

Login, credential remediation, and shell must provide at least:

```text
keyboard-reachable controls
proper labels for credential fields
visible focus
semantic navigation landmarks
non-color-only auth/error state
screen-readable loading/error text
```

## Responsive minimum for shell/auth

The shell, login page, and credential-remediation UX must remain usable at common desktop/laptop widths and narrow mobile browser widths.

M3.5.1 does not need final visual polish, but navigation, logout, and required credential remediation must remain reachable without horizontal-layout failure.

## Explicit non-goals

M3.5.1 does not implement:

```text
real Workbench data/cards
ReviewCase list/detail business surface
Finding/Action forms or commands
Notification Center records
Management aggregates
manual nudge
Scenario-specific field rendering beyond establishing future-compatible module boundaries
allowed_actions backend projection
new Review Core APIs
new auth token model
cross-origin browser deployment
CORS policy expansion
CSRF redesign
production scheduler/reminder infrastructure
WebSocket realtime
PWA/offline
full design system/theme platform
```

The narrow credential-remediation UX required by the existing Platform Core safety contract is not considered later-slice business scope.

## Proposed implementation scope after all prerequisites pass

A valid first executable frontend PR may introduce only what is necessary to prove this slice, for example:

```text
web/ React + TypeScript + Vite workspace
package manifest + lockfile
shared API client
auth provider/session + server credential-posture resolution
login page
credential-remediation page/flow
protected route wrapper
product shell/navigation
route placeholders
frontend tests
browser auth/credential acceptance
frontend CI integration
minimal development HTTPS/proxy setup
```

Backend executable changes remain out of the frontend PR because the credential prerequisite is reviewed and merged separately.

## M3.5.1 final architecture test

M3.5.1 succeeds only when the normal administrator-provisioned user journey works, not merely a fixture with `must_change_password=false`.

The critical flow is:

```text
system_admin creates ordinary local user
(default must_change_password=true)
        ↓
user opens Product Surface and logs in
        ↓
existing Secure HttpOnly server Session is established
        ↓
server reports password-change requirement
        ↓
Product Surface routes user to credential remediation
        ↓
BusinessIdentity remains blocked while requirement=true
        ↓
user completes reviewed server-owned password change
        ↓
server atomically clears must_change_password
+ applies reviewed Session/audit semantics
        ↓
Product Surface re-resolves server state
        ↓
credential ready
        ↓
normal authenticated shell + /me/workbench placeholder
        ↓
hard reload proves Session/current-user state remains server-owned
        ↓
logout revokes server Session + clears cookie/client protected state
        ↓
protected route becomes inaccessible
```

At no point may React clear `must_change_password`, bypass BusinessIdentity, persist an auth token, or infer credential readiness from frontend state.
