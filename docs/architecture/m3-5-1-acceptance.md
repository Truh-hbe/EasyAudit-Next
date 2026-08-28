# M3.5.1 Acceptance Gate — Product Shell, Authentication & Navigation

This Acceptance Gate defines the executable proof required before M3.5.1 can pass Final Review.

Baseline:

```text
main@b1bf32cd86b7adbb28220c502f8af7c9762fa667
```

This M3.5.1 Gate PR remains documentation-only. It must contain only:

```text
docs/architecture/m3-5-1-product-shell-auth-navigation.md
docs/architecture/m3-5-1-acceptance.md
```

No React source, `package.json`, lockfile, Vite config, Node CI, CORS middleware, CSRF implementation, backend API, migration, or deployment config belongs in the Gate PR itself.

Executable frontend work begins only after this Gate passes review **and** the separately reviewed M3.5.1 Credential Readiness Backend Prerequisite Gate has passed and its backend implementation has been merged.

## Scope preservation

M3.5.1 must preserve the approved M3.5 Architecture Gate and all merged M1–M3.4 semantics.

Acceptance fails if the implementation:

- changes the existing server Session model for frontend convenience;
- ignores or weakens the existing `must_change_password` safety contract;
- allows React to clear or override credential requirements locally;
- bypasses `BusinessIdentity` for a password-change-required user;
- adds a browser-readable authentication token;
- relaxes `Secure`, `HttpOnly`, or `SameSite=Strict`;
- introduces credentialed cross-origin Product Surface traffic;
- makes `system_admin` a business authorization bypass;
- builds a temporary second Workbench from Case/Finding/Action queries;
- introduces business lifecycle, overdue, recipient, or provenance logic into the shell;
- folds backend credential APIs casually into the React implementation instead of using the separately approved prerequisite; or
- implements later M3.5.2–M3.5.4 business surfaces inside this slice.

## Existing Session contract and required credential prerequisite

Acceptance must preserve the existing Session endpoints:

```text
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/me
```

and the existing cookie contract:

```text
__Host-easyaudit_session
Secure
HttpOnly
SameSite=Strict
Path=/
```

But Acceptance must **not** assume that login success or `GET /api/v1/me = 200` means the user is ready for business APIs.

The merged Platform Core already defines the counterexample:

```text
LocalCredential.must_change_password = true
        ↓
Session may still be valid
        ↓
AuthenticatedIdentity succeeds
        ↓
BusinessIdentity returns 403
Password change required before business APIs
```

Normal administrator-created local users default to `must_change_password=true`.

Therefore the M3.5.1 frontend cannot begin until a separately approved backend prerequisite provides a server-owned contract for:

```text
current-user credential requirement
+ authenticated self-service password change
+ reviewed Session behavior after password change
+ atomic clearing of must_change_password
+ platform audit behavior
```

Exact endpoint spelling is owned by that backend Gate. The frontend may only consume the merged reviewed result.

## Same-origin acceptance

Browser-visible Product Surface and API traffic must use one origin.

A valid production contract remains:

```text
https://easyaudit.example/
├── /          Product Surface
└── /api/v1/*  FastAPI
```

The Product Surface API client must use relative same-origin URLs, including any credential-remediation endpoint accepted by the prerequisite Gate.

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
mocking the entire login/session/credential boundary
```

## Initial source/workspace acceptance

After all prerequisite Gates pass, executable implementation should create a top-level:

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

The browser Session-resolution model remains limited to:

```text
resolving
anonymous
authenticated
```

`must_change_password` or its reviewed equivalent is **not** a fourth client-owned Session state. It is server-owned credential posture attached to an authenticated user.

Required conceptual split:

```text
authenticated
    │
    ├── credential ready
    │      → normal Product Surface
    │
    └── password change required
           → credential remediation UX
           → normal business access remains blocked by server
```

Cold protected-route acceptance:

```text
open protected route with no valid Session
→ auth begins resolving
→ server current-user resolution
→ 401
→ protected content never renders
→ user reaches /login
```

Credential-ready valid-session acceptance:

```text
open protected route with valid Session
→ auth begins resolving
→ server current-user resolution succeeds
→ server says credential ready
→ authenticated shell/route renders
```

Password-change-required valid-session acceptance:

```text
open protected route with valid Session
→ auth begins resolving
→ server current-user resolution succeeds
→ server says password change required
→ credential remediation UX renders
→ normal business placeholder/page does not render as available
```

A stale cached user object or cached credential flag must not be sufficient to bypass server resolution after reload.

## No protected-content flash

At least one component/browser test must demonstrate that protected content is not rendered during `resolving` and then hidden after a 401.

A second test must demonstrate that normal credential-ready Product Surface content is not rendered and then withdrawn after discovering a password-change requirement.

Forbidden sequences:

```text
render protected page
→ show sensitive cached content
→ current-user request returns 401
→ redirect login
```

```text
render normal business placeholder/page
→ call business API
→ receive password-change 403
→ only then discover credential requirement
```

Required ordering:

```text
resolve Session + server credential posture first
→ then choose login / credential remediation / normal route
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
→ Product Surface resolves server credential posture
```

For a credential-ready account:

```text
server says ready
→ navigate to /me/workbench or safe intended route
```

For the normal default administrator-created account:

```text
must_change_password=true
→ login still succeeds
→ Session remains valid
→ Product Surface routes to credential remediation
→ does not pretend business access is ready
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

## Credential requirement discovery acceptance

The Product Surface must discover the requirement from a reviewed server response, not from business-API failure inference.

Acceptance must prove a user with:

```text
must_change_password=true
```

can have:

```text
login = 200
valid Session
current-user/bootstrap resolution = authenticated + password-change-required
```

without React inventing the fact.

Source review must reject logic equivalent to:

```ts
if (lastBusinessError.status === 403) mustChangePassword = true
```

or:

```ts
mustChangePassword = localStorage.getItem("mustChangePassword") === "true"
```

## Credential remediation acceptance

After the backend prerequisite is merged, a real browser/PostgreSQL flow must prove:

```text
system_admin creates ordinary local user
(default must_change_password=true)
        ↓
user logs in successfully
        ↓
server Session valid
        ↓
server reports password-change requirement
        ↓
Product Surface shows credential remediation
        ↓
business API remains server-blocked while requirement=true
        ↓
user submits the reviewed authenticated password-change command
        ↓
server changes credential and atomically clears must_change_password
        ↓
server applies reviewed Session/audit semantics
        ↓
Product Surface re-resolves server state
        ↓
server reports credential ready
        ↓
normal Product Surface becomes available
```

Acceptance must prove:

```text
React cannot clear must_change_password locally
React cannot bypass BusinessIdentity
React cannot enable normal business access before server confirmation
```

The credential-remediation form must not persist current password, new password, or confirmation values in localStorage/sessionStorage.

## Server remains the business-access backstop

At least one backend/browser acceptance must explicitly prove that while the credential requirement is still true:

```text
valid Session
→ direct business API call
→ 403 Password change required before business APIs
```

The Product Surface remediation UX does not replace this backend enforcement.

After successful server-owned password change:

```text
same logical user
→ reviewed post-change Session state
→ BusinessIdentity succeeds
```

This is the core proof that the frontend consumed, rather than weakened, the existing safety contract.

## HttpOnly proof

Acceptance must include browser-level evidence that authentication and credential remediation succeed without JavaScript reading the Session cookie.

The implementation must not contain code that attempts to parse `document.cookie` for EasyAudit authentication.

Because the cookie is HttpOnly, Product Surface logic should have no need for its value.

## Browser storage acceptance

A browser acceptance check must confirm that after login and after credential remediation:

```text
localStorage
sessionStorage
```

contain no EasyAudit Session/authentication token, JWT, current password, new password, raw login credential, or locally authoritative credential-ready flag.

Non-sensitive presentation preferences are not forbidden by this rule.

## Current-user identity/posture acceptance

After login, the reviewed server current-user/bootstrap contract must provide the current server-authenticated user plus the credential requirement needed by M3.5.1.

Acceptance must prove the shell does not construct identity or credential readiness from a decoded token, user role, a business 403, or locally invented data.

The exact response shape is frozen by the prerequisite Gate; M3.5.1 must not maintain an incompatible frontend-only variant.

## Reload acceptance

Credential-ready flow:

```text
login successfully
→ navigate authenticated shell
→ hard reload browser page
→ React state is lost/recreated
→ server validates existing Session + credential posture
→ authenticated shell returns
```

Password-change-required flow:

```text
login successfully
→ server reports password change required
→ credential remediation shown
→ hard reload
→ server still reports password change required
→ remediation remains required
```

This proves persistence comes from server Session/credential state rather than JavaScript state.

## Expired/revoked Session acceptance

At least one test must prove:

```text
user is authenticated in browser
→ server Session becomes expired/revoked
→ browser performs protected API/session resolution
→ 401
→ protected client state is cleared
→ shell/remediation stops rendering protected content
→ user reaches safe login UX
```

The frontend must not keep the previous user authenticated because cached metadata exists.

## Login-route-with-valid-session acceptance

At least one test must cover:

```text
valid server Session exists
→ user opens /login
→ Product Surface resolves server Session + credential posture
```

If credential-ready:

```text
→ redirect to /me/workbench or safe internal destination
```

If password change required:

```text
→ route to credential remediation
```

This decision must be based on server resolution, not stale local metadata.

## Intended-route acceptance

If a user is redirected to login from a protected internal route, M3.5.1 may remember that internal destination.

Acceptance must prove:

```text
/protected/internal/path
→ login
→ successful auth
→ if credential ready: safe return to internal path
→ if password change required: remediation first, then safe return after server reports ready
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
→ frontend removes protected client state including credential-posture cache
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

## Password-change 403 handling is not Session expiry

A valid Session plus a password-change requirement is still authenticated.

Acceptance must reject logic that maps the existing business 403:

```text
Password change required before business APIs
```

to anonymous Session state.

The normal Product Surface should discover the credential requirement before business navigation. If the 403 is nevertheless observed because of stale/racing state, it must route back to server-owned credential resolution/remediation rather than clearing or fabricating the requirement locally.

## Shared API client acceptance

M3.5.1 must establish one shared API transport layer.

Code review must prove authentication and credential-remediation requests can share:

```text
relative same-origin transport
JSON handling
HTTP status/error mapping
401 session signal
server credential-requirement handling
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

or security authority such as:

```text
clearMustChangePasswordLocally()
forceCredentialReady()
```

## No bearer-token header acceptance

Source review must find no Product Surface logic equivalent to:

```text
Authorization: Bearer <frontend token>
```

for the EasyAudit Session flow.

The browser authenticates by the existing HttpOnly cookie.

## Product shell acceptance

After successful authentication and server confirmation that credentials are ready, the browser must show a stable application shell containing at least:

```text
EasyAudit product identity/header
current user display
primary navigation
logout action
main content outlet
```

For a password-change-required user, the Product Surface must show the minimal credential-remediation UX rather than falsely presenting ordinary business access as ready.

The shell itself must not fetch or calculate ReviewCase/Finding/Action business truth.

## Primary navigation acceptance

For credential-ready users, the approved primary areas remain visible/reachable according to shell presentation rules:

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

A password-change-required user must not use primary business navigation to circumvent the remediation requirement.

## Later-slice placeholder acceptance

Route placeholders are allowed only when they are explicit about scope and the authenticated user is credential-ready.

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

The shell may use server-returned `platform_role` to decide whether `/admin` navigation is useful to display once credential posture permits normal Product Surface navigation.

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

but source review must also prove `system_admin` is not reused to bypass business-resource authorization or credential readiness in Product Surface code.

## Direct-route backend authority

Frontend navigation visibility is UX only.

Acceptance must preserve the rule that direct backend calls remain independently protected by existing server dependencies/policies.

Hiding `/admin` from ordinary users or hiding business navigation from password-change-required users must not be treated as sufficient backend security.

## Unknown frontend route acceptance

An unknown Product Surface route must render a controlled 404/not-found UX or safe redirect.

It must not fall through to an API response or expose backend internals.

Production routing later must preserve `/api/v1/*` as backend-owned paths.

## Backend prerequisite separation acceptance

The M3.5.1 React implementation diff must not contain the backend credential change itself.

Before frontend implementation starts, the separately reviewed backend prerequisite must be merged and must own any required changes to:

```text
current-user response/bootstrap contract
password-change application service/command
credential persistence/locking
Session rotation/revocation semantics
platform audit facts
backend tests/OpenAPI
```

Acceptance fails if the React PR opportunistically edits `src/easyaudit_next/` to make credential remediation work.

If another backend need appears after the prerequisite is merged, M3.5.1 must stop and open another backend Gate rather than widening frontend scope.

## No speculative auth API acceptance

The credential prerequisite exists because of a proven current server contract. It must not become an excuse to add unrelated auth infrastructure.

The combined backend/frontend implementation must still reject speculative additions such as:

```text
/api/v1/auth/token
/api/v1/auth/refresh
frontend bearer tokens
browser-readable Session secrets
credentialed cross-origin auth transport
```

unless independently justified by a future Gate.

## No CORS middleware acceptance

Source diff review must prove M3.5.1 does not add broad CORS middleware or a credentialed cross-origin allowlist merely to connect React and FastAPI.

Development must solve this with same-origin proxying, not by changing the authentication trust boundary.

## Backend application preservation

Unless separately gated, `src/easyaudit_next/main.py` remains an API composition root rather than becoming a place for ad hoc frontend auth/security policy.

The credential prerequisite may make reviewed Platform/API changes, but those must remain narrow and explicit. Production static hosting/reverse-proxy integration must preserve the approved same-origin contract and must not alter backend domain semantics.

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

Browser auth/credential acceptance may run in the same workflow or a dedicated job.

## Real-browser authentication proof

M3.5.1 Final Review must include browser automation against actual FastAPI + PostgreSQL, not only mocked React tests.

It must cover at least two real flows.

Credential-ready flow:

```text
unauthenticated protected route
→ login
→ server confirms credential ready
→ authenticated shell
→ hard reload
→ current-user resolution
→ logout
→ protected route denied
```

Default provisioned-user flow:

```text
admin creates user with default must_change_password=true
→ user logs in successfully
→ Product Surface recognizes server requirement
→ credential remediation
→ server-owned password change succeeds
→ requirement clears on server
→ business access becomes available
→ reload
→ logout
```

These are the critical proofs that Product Surface really consumes the Platform Core security contract.

## Browser cookie assertions

The real-browser acceptance should verify the Session cookie has the intended effective properties wherever the test framework exposes them:

```text
name = __Host-easyaudit_session
secure = true
httpOnly = true
sameSite = Strict
path = /
```

If the backend prerequisite rotates/reissues the current Session cookie after password change, the same effective properties must be preserved.

If a framework cannot directly expose every flag, HTTP response/header evidence may supplement browser behavior proof, but existing backend cookie tests must not be weakened.

## Cross-user cache isolation acceptance

At least one test or explicit client-state unit test must prove protected cached state does not survive a user boundary.

Example:

```text
User A authenticated
→ client holds current-user/credential/protected state
→ logout/session expiry
→ protected state cleared
→ User B logs in
→ User A data or credential posture is not rendered from old client cache
```

M3.5.1 currently has little business data, but this clearing contract must be established before later slices add sensitive server-query caches.

## Accessibility acceptance

Login, credential remediation, and shell must pass basic checks for:

```text
keyboard reachability
visible focus
labeled credential controls
semantic navigation landmark
accessible logout action
loading/error text not conveyed by color alone
```

A full design-system accessibility program is deferred, not ignored.

## Responsive acceptance

At minimum, browser/component acceptance must inspect login, credential remediation, and shell at:

```text
common desktop/laptop width
narrow mobile browser width
```

Primary navigation, logout, and required password change must remain reachable without horizontal-layout breakage.

M3.5.1 is responsive Web, not a native app or offline PWA.

## Forbidden business/security truth in M3.5.1

Source review should fail the slice if shell/auth code contains business-authoritative rules equivalent to:

```ts
if (user.platform_role === "system_admin") canOpenAnyCase = true
if (finding.lifecycle === "verifying") canApprove = true
if (action.dueAt < now) action.isOverdue = true
recipients = finding.owners
```

or credential-authoritative rules equivalent to:

```ts
mustChangePassword = false // after local form submit
credentialReady = true     // without server confirmation
```

None belong in Product Shell authentication/navigation.

## No second Session model

Acceptance must reject frontend entities/state machines that duplicate server Session lifecycle beyond simple browser resolution.

Allowed:

```text
resolving / anonymous / authenticated
current user metadata
server-returned credential requirement
```

The server-returned credential requirement is presentation/input to routing, not a client-owned credential state machine.

Not allowed:

```text
frontend refresh-token lifecycle
frontend token expiry authority
frontend Session aggregate
browser-generated Session IDs
client-side Session revocation truth
client-side credential requirement authority
```

## Final M3.5.1 user journeys

The original shell journey remains required for a credential-ready account:

```text
1. User opens /me/workbench without a Session
2. Product Surface resolves server state and receives 401
3. No protected shell content is exposed
4. User reaches /login
5. User submits valid credentials
6. FastAPI creates existing server Session and Secure HttpOnly cookie
7. Server reports credential ready
8. Product Surface renders authenticated shell
9. Default destination is /me/workbench
10. Primary navigation is reachable; later slices are honest placeholders
11. Hard reload revalidates server Session/credential posture
12. No auth token exists in localStorage/sessionStorage
13. User invokes logout
14. FastAPI revokes Session and clears cookie
15. Product Surface clears protected client state
16. /me/workbench is no longer accessible without login
```

A second journey is mandatory because it represents the normal default admin-provisioned user:

```text
1. system_admin creates ordinary local user with default must_change_password=true
2. User logs in; login succeeds and Session is valid
3. Product Surface receives server-owned password-change requirement
4. Normal business access remains blocked by BusinessIdentity
5. Product Surface shows credential remediation
6. User completes reviewed server-owned password-change command
7. Server atomically updates credential and clears must_change_password
8. Reviewed Session/audit semantics complete successfully
9. Product Surface re-resolves server state
10. Server reports credential ready
11. BusinessIdentity now permits business APIs
12. Normal Product Surface becomes available
```

Any implementation that makes step 7 or 10 a frontend-only state change fails Acceptance.

## Fixed-head review evidence

M3.5.1 cannot pass Final Review without:

```text
merged fixed-head evidence for credential-readiness backend prerequisite
exact frontend implementation head SHA
PR state/base/head verification
full changed-file review
frontend CI success
existing backend CI success
browser Session + credential-remediation acceptance success
scope proof against approved M3.5.1 Gate
```

A green build with only a `must_change_password=false` fixture is insufficient.

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

The minimal credential-remediation Product Surface needed to honor the existing Platform Core requirement is explicitly in scope.

## Final invariant checklist

M3.5.1 cannot pass unless all are true:

```text
browser-visible Product Surface/API remain same-origin
existing __Host-easyaudit_session semantics remain Secure/HttpOnly/Strict
no JavaScript-readable auth token
no auth token or password in localStorage/sessionStorage
Session resolution remains server-authoritative
credential readiness remains server-authoritative
must_change_password=true is represented, not bypassed
normal default-created user can complete server-owned remediation
React cannot clear must_change_password locally
BusinessIdentity remains blocked until server clears requirement
protected content waits for Session + credential-posture resolution
logout invokes backend logout and clears protected caches
401 Session expiry clears protected client state
password-change 403 is not misclassified as Session expiry
system_admin is not a business or credential bypass
shared API client contains transport, not business/security authority
no broad credentialed CORS
no temporary second Workbench or other later-slice domain
frontend CI is deterministic
real browser proves login → credential remediation when required → reload → logout against FastAPI + PostgreSQL
```

M3.5.1 succeeds when the first Web shell is genuinely usable for **normally provisioned users**, while remaining a consumer of server-owned Session, credential, authorization, and business truth.
