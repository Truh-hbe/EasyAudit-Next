# M3.5.1 — Product Shell, Authentication & Navigation Implementation Gate

M3.5.1 is the first executable slice under the approved M3.5 Product Surface architecture.

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

Executable M3.5.1 work begins only after this Gate is explicitly accepted.

## Goal

M3.5.1 establishes the minimum long-lived browser application foundation required by later M3.5 slices:

```text
browser shell
+ existing server Session authentication
+ protected-route resolution
+ primary navigation
+ same-origin API client boundary
+ safe logout/session-expiry behavior
+ empty/placeholder product routes for later slices
```

It does **not** implement Workbench business content, ReviewCase details, Finding/Action collaboration, Notification Center, Management projections, or Reminder actions. Those remain M3.5.2–M3.5.4.

The M3.5.1 invariant is:

> **The browser may know whether it currently has an authenticated server Session and may navigate the product shell, but it does not acquire a second authentication authority, business authorization model, or domain cache.**

## Existing authentication contract being consumed

M3.5.1 must consume the already-merged M1 authentication endpoints and cookie behavior as-is.

Existing endpoints:

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

The Product Surface must not require a new browser-readable access token, refresh token, JWT, bearer token, or frontend session secret.

`LoginResponse.session_id` is metadata, not a bearer credential. The browser application must not treat it as an authentication token or persist it as one.

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

It must not embed a separate production API origin into feature code.

The implementation must not introduce a credentialed cross-origin browser security model merely for development convenience.

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

Executable implementation, once approved, should create one top-level frontend workspace:

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

The browser application may own only a small **session-resolution state**, not a second Session domain.

Minimum states:

```text
resolving
anonymous
authenticated(current user metadata)
```

On cold start for a protected route:

```text
app starts
→ auth = resolving
→ GET /api/v1/me
   ├── 200 → authenticated
   └── 401 → anonymous
```

Protected content must not render before this resolution finishes.

The browser must not decide an existing Session is valid merely because cached user metadata exists.

A page reload therefore re-enters `/api/v1/me` server validation.

## Login behavior

The login page submits credentials only to:

```text
POST /api/v1/auth/login
```

The browser receives the server-managed HttpOnly cookie through the normal same-origin response.

React does not read the cookie value and does not need to know it.

On successful login:

```text
POST login → 200
→ auth state becomes authenticated from server-returned user data
→ navigate to intended protected destination when safe
   otherwise /me/workbench
```

On invalid credentials:

```text
401
→ remain anonymous
→ show non-sensitive login error
→ do not create local auth state
```

Credentials must not be persisted in localStorage/sessionStorage.

## Current-user identity boundary

`GET /api/v1/me` is the browser bootstrap source for current user identity.

The UI may use returned platform metadata such as display name and `platform_role` for presentation/navigation hints.

Important distinction:

```text
platform_role
→ may influence platform-admin navigation presentation

platform_role
≠ ReviewCase/Finding/Action business authorization
```

M3.5.1 must not convert `system_admin` into a global business permission shortcut.

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

For authenticated Product Surface requests, a server 401 means the browser must stop treating the current session as authenticated.

M3.5.1 must provide one centralized path equivalent to:

```text
401 from protected API
→ clear protected client state
→ auth = anonymous
→ navigate/show safe login UX
```

This must not expose stale protected page content behind a login overlay.

Login's own expected `401 Invalid credentials` is handled as login failure, not as an authenticated-session-expiry event.

## Shared API client boundary

M3.5.1 establishes one reusable transport boundary for later slices.

Responsibilities:

```text
same-origin relative request URLs
JSON request/response handling
standard error object containing HTTP status + safe detail
401 signaling to auth/session layer
AbortSignal/request cancellation support where practical
no embedded business authorization logic
```

Feature modules must not scatter direct production `fetch()` implementations with inconsistent auth/error semantics.

The API client must not:

```text
read/write the HttpOnly cookie
attach a custom bearer token
select reminder recipients
infer workflow permission
infer lifecycle transition legality
recompute overdue truth
```

M3.5.1 only needs typed transport contracts for the authentication/current-user APIs it consumes. Broader OpenAPI client generation may be added incrementally in later slices, but handwritten DTOs must remain wire representations.

## Product shell

The authenticated shell establishes stable global chrome only:

```text
application identity/header
primary navigation
current user display
logout action
main route outlet
loading/error/session-expiry states
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

Default authenticated landing route:

```text
/me/workbench
```

## Navigation and slice boundaries

M3.5.1 may create route placeholders for later Product Surface slices so the shell and route tree are stable.

Conceptual routes:

```text
/login

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
→ authenticated shell + explicit "Workbench surface arrives in M3.5.2" state
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
→ resolve current server session
→ if authenticated, render shell/route
→ if anonymous, navigate to /login
```

The application must avoid:

```text
render protected data
→ later discover 401
→ flash hidden content
```

A remembered intended destination may be used after successful login, but it must be an internal Product Surface path, not an arbitrary external redirect target.

Open-redirect behavior is forbidden.

## `/login` behavior for an existing valid Session

Visiting `/login` while a valid server Session already exists should not create a second login authority.

The route may resolve `/api/v1/me` and redirect an already-authenticated user to `/me/workbench` or another safe internal destination.

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
business authorization snapshot used as authority
```

Authentication state should be reconstructible from the server Session via `/api/v1/me`.

## Cache-clearing boundary

M3.5.1 must establish a single conceptual operation for removing protected browser data when authentication ends.

It must clear at least:

```text
current-user cached data
protected route data owned by the current runtime
future registered server-query caches
sensitive transient state that should not cross users
```

The mechanism may evolve as later slices add query caches, but logout/session expiry must have one reliable clearing boundary rather than feature-by-feature cleanup.

## No backend auth expansion in M3.5.1

M3.5.1 must not add an endpoint solely to make the frontend easier if the existing contract already answers the question.

In particular, no need is currently established for:

```text
/api/v1/auth/token
/api/v1/auth/refresh
/api/v1/auth/session
/api/v1/ui/permissions
frontend-specific login endpoint
```

`POST login`, `POST logout`, and `GET /api/v1/me` are sufficient for the shell authentication loop.

Any backend API change discovered during implementation must stop and return to a separate backend Gate rather than being folded casually into the React PR.

## No CORS/CSRF scope expansion

Because M3.5.1 uses the approved same-origin browser contract, it must not add broad CORS middleware or redesign CSRF policy as speculative infrastructure.

The absence of cross-origin Product Surface traffic is intentional.

If implementation discovers that a new browser-origin relationship is actually required, M3.5.1 pauses and re-enters the Authentication / Browser Security Architecture Gate defined by M3.5.

## CI boundary for executable implementation

Once this Gate is approved and executable work starts, CI must preserve all existing backend checks and add deterministic frontend checks.

At minimum the implementation fixed head should run:

```text
existing Python/PostgreSQL CI unchanged
+ frontend dependency install from lockfile
+ TypeScript typecheck
+ frontend lint/static checks
+ unit/component tests
+ production frontend build
```

At least one browser-level acceptance test is required for the real authentication loop because HttpOnly/Secure cookie behavior cannot be proven by component tests alone.

A browser framework such as Playwright is acceptable. Exact tooling is an implementation choice, but the acceptance must exercise a real browser cookie jar against the actual FastAPI auth contract.

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

Tests must not replace the real cookie with a fake localStorage token or stub the entire authentication boundary.

Component tests may mock APIs for presentation behavior, but the fixed-head authentication proof must include the actual backend login/session/logout path.

## Error handling in this slice

M3.5.1 must provide understandable UX for:

```text
invalid credentials
session expired
backend unavailable
unexpected login/logout failure
unknown frontend route
```

Error handling must not leak password values or auth secrets.

## Accessibility minimum for shell/auth

This first slice already participates in the final M3.5 accessibility contract.

Login and shell must provide at least:

```text
keyboard-reachable controls
proper labels for login fields
visible focus
semantic navigation landmarks
non-color-only auth/error state
screen-readable loading/error text
```

## Responsive minimum for shell/auth

The shell and login page must remain usable at common desktop/laptop widths and narrow mobile browser widths.

M3.5.1 does not need final visual polish, but navigation and logout must remain reachable without horizontal-layout failure.

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

## Proposed implementation scope after Gate approval

A valid first executable PR may introduce only what is necessary to prove this slice, for example:

```text
web/ React + TypeScript + Vite workspace
package manifest + lockfile
shared API client
auth provider/session resolution
login page
protected route wrapper
product shell/navigation
route placeholders
frontend tests
browser auth acceptance
frontend CI integration
minimal development HTTPS/proxy setup
```

Backend executable changes are out of scope unless separately gated.

## M3.5.1 final architecture test

M3.5.1 succeeds when a user can open the Web product in a real browser and complete:

```text
anonymous visit to protected route
→ safe login page
→ login through existing FastAPI endpoint
→ browser receives unchanged HttpOnly Secure Session cookie
→ Product Surface reaches authenticated shell
→ /api/v1/me confirms identity
→ primary navigation is usable
→ reload preserves access only because server Session remains valid
→ logout revokes server Session + clears cookie/client protected state
→ protected route becomes inaccessible
```

while no frontend token, CORS security model, business authorization shortcut, or fake domain surface has been introduced.
