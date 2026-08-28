# M3.5.1 Acceptance Gate — Product Shell, Authentication & Navigation

This Acceptance Gate defines the executable proof required before M3.5.1 can pass Final Review.

Baseline:

```text
main@b1bf32cd86b7adbb28220c502f8af7c9762fa667
```

This initial M3.5.1 Gate PR is documentation-only. It must contain only:

```text
docs/architecture/m3-5-1-product-shell-auth-navigation.md
docs/architecture/m3-5-1-acceptance.md
```

No React source, `package.json`, lockfile, Vite config, Node CI, CORS middleware, CSRF implementation, backend API, migration, or deployment config belongs in the Gate PR itself.

Executable work begins only after this Gate passes review.

## Scope preservation

M3.5.1 must preserve the approved M3.5 Architecture Gate and all merged M1–M3.4 semantics.

Acceptance fails if the implementation:

- changes the existing server Session model for frontend convenience;
- adds a browser-readable authentication token;
- relaxes `Secure`, `HttpOnly`, or `SameSite=Strict`;
- introduces credentialed cross-origin Product Surface traffic;
- makes `system_admin` a business authorization bypass;
- builds a temporary second Workbench from Case/Finding/Action queries;
- introduces business lifecycle, overdue, recipient, or provenance logic into the shell;
- adds backend APIs without a separately approved backend Gate; or
- implements later M3.5.2–M3.5.4 business surfaces inside this slice.

## Fixed backend authentication contract

Acceptance must use the existing endpoints exactly as the browser authentication loop:

```text
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/me
```

The implementation must continue to work with the existing cookie contract:

```text
__Host-easyaudit_session
Secure
HttpOnly
SameSite=Strict
Path=/
```

Acceptance fails if Product Surface correctness depends on changing these semantics.

## Same-origin acceptance

Browser-visible Product Surface and API traffic must use one origin.

A valid production contract remains:

```text
https://easyaudit.example/
├── /          Product Surface
└── /api/v1/*  FastAPI
```

The Product Surface API client must use relative same-origin URLs.

Code review must reject:

```text
https://api.example.com embedded in feature code
credentials: include used to create a separate-origin session architecture
CORS wildcard/broad session configuration
SameSite relaxation for React
JavaScript-readable copy of the Session token
```

Development proxying is acceptable only when the browser still observes one origin.

## Secure-cookie development acceptance

Because the cookie remains `Secure`, the browser-level implementation proof must run in an environment where the unchanged Secure cookie is genuinely accepted and returned.

Preferred explicit development/test shape:

```text
HTTPS browser origin
├── Vite / Product Surface
└── /api/v1/* proxy → FastAPI
```

Acceptance must reject a test setup that proves auth only by:

```text
setting Secure=False
renaming the cookie
placing a token in localStorage
injecting a fake authenticated React state
mocking the entire login/session boundary
```

## Initial source/workspace acceptance

After Gate approval, executable implementation should create a top-level:

```text
web/
```

Acceptance must prove frontend application source is not mixed into `src/easyaudit_next/` domain/backend packages.

The frontend workspace must be independently buildable from a committed lockfile.

## Toolchain acceptance

The first executable slice must provide deterministic commands for at least:

```text
install from lockfile
typecheck
lint/static checks
unit/component tests
production build
```

CI must run those checks in addition to the existing Python/PostgreSQL pipeline.

The implementation must not remove or weaken existing Ruff, mypy, architecture, OpenAPI, Alembic, or PostgreSQL pytest checks.

## Authentication state acceptance

The browser session-resolution model must distinguish at least:

```text
resolving
anonymous
authenticated
```

Cold protected-route acceptance:

```text
open protected route with no valid Session
→ auth begins resolving
→ GET /api/v1/me
→ 401
→ protected content never renders
→ user reaches /login
```

Valid-session acceptance:

```text
open protected route with valid Session
→ auth begins resolving
→ GET /api/v1/me
→ 200
→ authenticated shell renders
```

A stale cached user object must not be sufficient to bypass `/api/v1/me` resolution after reload.

## No protected-content flash

At least one component/browser test must demonstrate that protected route content is not rendered during `resolving` and then hidden after a 401.

Forbidden sequence:

```text
render protected page
→ show sensitive cached content
→ GET /me returns 401
→ redirect login
```

Required sequence:

```text
resolve Session first
→ then render protected route
```

## Login acceptance

A real browser-level test must prove:

```text
anonymous browser
→ visit /login
→ submit valid login name/password
→ POST /api/v1/auth/login
→ response succeeds
→ browser stores server-issued __Host-easyaudit_session
→ JavaScript does not receive/read cookie value
→ Product Surface becomes authenticated
→ navigate to /me/workbench or safe intended route
```

The test must use the actual FastAPI authentication endpoint and actual PostgreSQL-backed Session behavior.

Invalid credentials acceptance:

```text
POST login → 401
→ remain anonymous
→ login form stays usable
→ generic/non-sensitive error shown
→ no local authenticated state created
```

Passwords must never be stored in browser storage.

## HttpOnly proof

Acceptance must include browser-level evidence that authentication succeeds without JavaScript reading the Session cookie.

The implementation must not contain code that attempts to parse `document.cookie` for EasyAudit authentication.

Because the cookie is HttpOnly, Product Surface logic should have no need for its value.

## Browser storage acceptance

A browser acceptance check must confirm that after successful login:

```text
localStorage
sessionStorage
```

contain no EasyAudit session/authentication token, JWT, password, or raw login credential.

Non-sensitive presentation preferences are not forbidden by this rule.

## `/api/v1/me` identity acceptance

After login, `GET /api/v1/me` must return the current server-authenticated user and the shell must use that response/server-returned user metadata for identity presentation.

Acceptance must prove the shell does not construct a user identity from a decoded token or locally invented role data.

## Reload acceptance

Real-browser flow:

```text
login successfully
→ navigate authenticated shell
→ hard reload browser page
→ React state is lost/recreated
→ GET /api/v1/me validates existing server Session
→ authenticated shell returns
```

This proves persistence comes from the server Session cookie rather than JavaScript token persistence.

## Expired/revoked Session acceptance

At least one test must prove:

```text
user is authenticated in browser
→ server Session becomes expired/revoked
→ browser performs protected API/session resolution
→ 401
→ protected client state is cleared
→ shell stops rendering protected content
→ user reaches safe login UX
```

The frontend must not keep the previous user authenticated because cached metadata exists.

## Login-route-with-valid-session acceptance

At least one test must cover:

```text
valid server Session exists
→ user opens /login
→ Product Surface resolves server Session
→ does not present a misleading second local login state
→ redirects to /me/workbench or other safe internal destination
```

This decision must be based on server Session resolution, not stale local metadata.

## Intended-route acceptance

If a user is redirected to login from a protected internal route, M3.5.1 may remember that internal destination.

Acceptance must prove:

```text
/protected/internal/path
→ login
→ successful auth
→ safe return to internal path
```

and reject open redirects such as:

```text
/login?next=https://attacker.example/
```

Only validated internal Product Surface paths may be used as return destinations.

## Logout acceptance

A real browser-level test must prove:

```text
authenticated browser
→ invoke logout
→ POST /api/v1/auth/logout
→ backend revokes current Session
→ response clears existing cookie contract
→ frontend removes protected client state
→ auth becomes anonymous
→ browser is sent to /login
→ reopening protected route requires authentication
```

The acceptance must verify server-side invalidation, not merely React state reset.

## Already-expired logout behavior

If logout encounters a Session that is already invalid/expired, Product Surface must still remove protected client state and transition to anonymous UX.

No local token-revocation mechanism may be invented.

## Logout failure honesty

For a network/5xx failure during logout:

- protected content should be removed from the currently displayed client state for confidentiality;
- UI must not falsely claim server-side Session revocation was confirmed;
- no browser-readable token blacklist or local auth authority is introduced.

The exact retry/error copy is an implementation detail.

## Central 401 handling acceptance

Authenticated feature/API requests must share one session-expiry path.

Acceptance must prove a protected request returning 401 can trigger:

```text
clear protected client state
→ anonymous auth state
→ safe login UX
```

without every feature inventing its own Session handling.

The login endpoint's expected invalid-credential 401 must remain an ordinary login error and must not create redirect loops.

## Shared API client acceptance

M3.5.1 must establish one shared API transport layer.

Code review must prove authentication requests and future feature requests can share:

```text
relative same-origin transport
JSON handling
HTTP status/error mapping
401 session signal
request cancellation support where practical
```

Acceptance fails if route/components directly proliferate inconsistent production `fetch()` calls with their own authentication assumptions.

The shared client must not add business logic such as:

```text
canApprove
canReject
isOverdue
resolveRecipients
lifecycle transition inference
```

## No bearer-token header acceptance

Source review must find no Product Surface logic equivalent to:

```text
Authorization: Bearer <frontend token>
```

for the existing EasyAudit Session flow.

The browser authenticates by the existing HttpOnly cookie.

## Product shell acceptance

After successful authentication, the browser must show a stable application shell containing at least:

```text
EasyAudit product identity/header
current user display
primary navigation
logout action
main content outlet
```

The shell itself must not fetch or calculate ReviewCase/Finding/Action business truth.

## Primary navigation acceptance

The approved primary areas remain visible/reachable according to shell presentation rules:

```text
我的工作
审查活动
通知
管理视图
管理设置
```

Default authenticated destination:

```text
/me/workbench
```

M3.5.1 does not need to implement the business content behind later-slice routes.

## Later-slice placeholder acceptance

Route placeholders are allowed only when they are explicit about scope.

For example:

```text
/me/workbench
→ shell + explicit M3.5.2 placeholder
```

Acceptance must reject a shortcut implementation that queries Cases/Findings/Actions and constructs a temporary Workbench before M3.5.2.

Similarly:

```text
/me/notifications
/management
```

must not fabricate Notification/Management data in this slice.

## Navigation-to-original-resource invariants

Although original resource detail pages arrive later, M3.5.1 routing structure must not introduce second detail-domain concepts such as:

```text
WorkbenchTaskDetail
NotificationOwnedObject
ManagementIssueDetail
```

Future routes remain pointers to original ReviewCase/Finding/ActionItem resources as defined by the M3.5 Architecture Gate.

## Platform-admin navigation acceptance

The shell may use server-returned `platform_role` to decide whether `/admin` navigation is useful to display.

Acceptance must include an ordinary-user case proving:

```text
ordinary_user
→ no frontend claim of admin authority
```

and a `system_admin` case proving:

```text
system_admin
→ admin navigation may be presented
```

but source review must also prove `system_admin` is not reused to bypass business-resource authorization in Product Surface code.

## Direct-route backend authority

Frontend navigation visibility is UX only.

Acceptance must preserve the rule that direct backend calls remain independently protected by existing server dependencies/policies.

Hiding `/admin` from ordinary users must not be treated as sufficient backend security.

## Unknown frontend route acceptance

An unknown Product Surface route must render a controlled 404/not-found UX or safe redirect.

It must not fall through to an API response or expose backend internals.

Production routing later must preserve `/api/v1/*` as backend-owned paths.

## No backend API expansion acceptance

The M3.5.1 executable diff must not add backend endpoints unless a new backend Gate has been explicitly accepted.

In particular, acceptance should reject opportunistic additions such as:

```text
/api/v1/auth/token
/api/v1/auth/refresh
/api/v1/auth/session
/api/v1/ui/bootstrap
/api/v1/ui/permissions
```

unless separately justified and reviewed.

The existing login/logout/me contract is sufficient for this slice.

## No CORS middleware acceptance

Source diff review must prove M3.5.1 does not add broad CORS middleware or a credentialed cross-origin allowlist merely to connect React and FastAPI.

Development must solve this with same-origin proxying, not by changing the authentication trust boundary.

## Backend application preservation

Unless separately gated, `src/easyaudit_next/main.py` remains an API composition root rather than becoming a place for ad hoc frontend auth/security policy.

M3.5.1 may later require production static hosting/reverse-proxy integration, but that infrastructure must preserve the approved same-origin contract and must not alter backend domain semantics.

If static hosting requires an executable backend change, that change must be explicitly listed and reviewed rather than hidden in shell implementation.

## Frontend CI acceptance

The implementation fixed head must add deterministic frontend checks while retaining all backend checks.

Minimum evidence:

```text
frontend install from lockfile     ✅
TypeScript typecheck               ✅
frontend lint/static check         ✅
unit/component tests               ✅
production build                   ✅
existing backend CI                ✅
```

Browser auth acceptance may run in the same workflow or a dedicated job.

## Real-browser authentication proof

M3.5.1 Final Review must include at least one browser automation flow against actual FastAPI + PostgreSQL, not only mocked React tests.

The browser flow must cover at minimum:

```text
unauthenticated protected route
→ login
→ authenticated shell
→ hard reload
→ current-user resolution
→ logout
→ protected route denied
```

This is the critical proof that the Product Surface really consumes the M1 server Session contract.

## Browser cookie assertions

The real-browser acceptance should verify the Session cookie has the intended effective properties where the test framework exposes them:

```text
name = __Host-easyaudit_session
secure = true
httpOnly = true
sameSite = Strict
path = /
```

If a framework cannot directly expose every flag, HTTP response/header evidence may supplement the browser behavior proof, but the implementation must not weaken the existing backend test coverage.

## Cross-user cache isolation acceptance

At least one test or explicit client-state unit test must prove protected cached state does not survive a user boundary.

Example:

```text
User A authenticated
→ client holds current-user/protected state
→ logout/session expiry
→ protected state cleared
→ User B logs in
→ User A data is not rendered from old client cache
```

M3.5.1 currently has little business data, but this clearing contract must be established before later slices add sensitive server-query caches.

## Accessibility acceptance

Login and shell must pass basic checks for:

```text
keyboard reachability
visible focus
labeled username/password controls
semantic navigation landmark
accessible logout action
loading/error text not conveyed by color alone
```

A full design-system accessibility program is deferred, not ignored.

## Responsive acceptance

At minimum, browser/component acceptance must inspect the login and shell at:

```text
common desktop/laptop width
narrow mobile browser width
```

Primary navigation and logout must remain reachable without horizontal-layout breakage.

M3.5.1 is responsive Web, not a native app or offline PWA.

## Forbidden business truth in M3.5.1

Source review should fail the slice if shell/auth code contains business-authoritative rules equivalent to:

```ts
if (user.platform_role === "system_admin") canOpenAnyCase = true
if (finding.lifecycle === "verifying") canApprove = true
if (action.dueAt < now) action.isOverdue = true
recipients = finding.owners
```

None of these belong in Product Shell authentication/navigation.

## No second Session model

Acceptance must reject frontend entities/state machines that duplicate server Session lifecycle beyond simple browser resolution.

Allowed:

```text
resolving / anonymous / authenticated
current user metadata
```

Not allowed:

```text
frontend refresh-token lifecycle
frontend token expiry authority
frontend Session aggregate
browser-generated Session IDs
client-side Session revocation truth
```

## Final M3.5.1 user journey

Final browser acceptance must demonstrate:

```text
1. User opens /me/workbench without a Session
2. Product Surface resolves /api/v1/me and receives 401
3. No protected shell content is exposed
4. User reaches /login
5. User submits valid credentials
6. FastAPI login creates existing server Session and Secure HttpOnly cookie
7. Product Surface renders authenticated shell
8. Default destination is /me/workbench
9. Primary navigation is reachable; later slices are honest placeholders
10. Hard reload revalidates via /api/v1/me and remains authenticated
11. No auth token exists in localStorage/sessionStorage
12. User invokes logout
13. FastAPI revokes Session and clears cookie
14. Product Surface clears protected client state
15. /me/workbench is no longer accessible without login
```

## Fixed-head review evidence

M3.5.1 cannot pass Final Review without:

```text
exact implementation head SHA
PR state/base/head verification
full changed-file review
frontend CI success
existing backend CI success
browser authentication acceptance success
scope proof against approved M3.5.1 Gate
```

A green build without browser Session proof is insufficient.

## Explicit non-goals

M3.5.1 Final Review must not require or reward scope expansion into:

```text
Workbench business data
ReviewCase business surface
Finding/Action collaboration
Notification Center
Management analytics
Reminder/nudge commands
Scenario-specific business renderer
allowed_actions backend projection
cross-origin deployment
new auth tokens
CORS expansion
CSRF redesign
scheduler/cadence
WebSocket realtime
PWA/offline
full theme/design-system platform
```

## Final invariant checklist

M3.5.1 cannot pass unless all are true:

```text
browser-visible Product Surface/API remain same-origin
existing __Host-easyaudit_session semantics unchanged
no JavaScript-readable auth token
no auth token in localStorage/sessionStorage
/api/v1/me is server Session resolution authority
protected content waits for Session resolution
logout invokes existing backend logout and clears protected caches
401 session expiry clears protected client state
system_admin is not a business bypass
shared API client contains transport, not business policy
no broad credentialed CORS
no temporary second Workbench or other later-slice domain
frontend CI is deterministic
real browser proves login → reload → logout against FastAPI + PostgreSQL
```

M3.5.1 succeeds when the first Web shell is genuinely usable and secure while remaining only a consumer of the already-frozen EasyAudit authentication and business architecture.
