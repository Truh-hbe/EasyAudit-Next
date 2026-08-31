# M6-Ops Operational Readiness Foundation Acceptance

## Acceptance principle

M6-Ops passes only when every operational guarantee is demonstrated by
machine-verifiable evidence against the real application architecture.

Nominal configuration or the presence of an endpoint is not sufficient
acceptance evidence.

The slice must prove:

```text
probe behavior
request correlation
secret-safe structured telemetry
bounded database behavior
bounded authentication cost
bounded Session writes
frontend failure containment
safe retry semantics
reproducible Python dependency resolution
```

while proving that Review Core and Scenario business behavior did not move.

# 1. Scope and architecture acceptance

The candidate must satisfy all of the following:

- no production change under `src/easyaudit_next/review_core/**`;
- no production change under `src/easyaudit_next/scenarios/**`;
- no Review lifecycle/authorization/recipient semantic change;
- no new Review aggregate or Review Activity type for operations;
- no database migration or new persistence table;
- operational logs/metrics are not used as business truth; and
- full existing Review Core/Scenario regression remains green.

Architecture tests must prevent the operational layer from becoming a Review
Core dependency.

Any implementation that requires a Review Core domain modification is No-Go
and reopens the Architecture Gate.

# 2. Health acceptance

## 2.1 Liveness is database-independent

With PostgreSQL deliberately unavailable:

```http
GET /health/live
```

must return HTTP 200 within a bounded local interval.

The test must prove the handler performs no database checkout/query and does
not expose database URL, credential, raw exception or migration detail.

## 2.2 Ready on exact migrated database

Against real PostgreSQL after:

```text
alembic upgrade head
```

`GET /health/ready` returns HTTP 200 and reports bounded `database=ok` /
`schema=ok` state.

## 2.3 Database outage

With FastAPI alive and PostgreSQL unavailable:

```text
/health/live  -> 200
/health/ready -> 503
```

Readiness must fail within the configured bounded connection/pool timeout; it
must not hang indefinitely.

## 2.4 Database behind code

On an isolated real PostgreSQL database at the previous valid Alembic revision:

```text
/health/ready -> 503
```

No migration is automatically executed by the readiness check.

## 2.5 Unexpected/future/diverged head

If the database current head set is not exactly equal to the code head set,
including an unexpected/future value:

```text
/health/ready -> 503
```

The comparison must be set equality through Alembic metadata, not a hard-coded
single revision or an ordinal `>=` assumption.

## 2.6 Health has no side effects

Repeated readiness calls leave unchanged:

```text
alembic_version
PlatformAuditEvent
AuthSession
Review data
Notification data
Activity data
```

except for no mutation at all to `alembic_version` itself.

## 2.7 Canonical CI uses readiness

The canonical real FastAPI/browser startup path waits for `/health/ready`, not
legacy static `/health`.

A workflow/script contract assertion should prevent accidental regression.

# 3. Request-ID acceptance

For a request without `X-Request-ID`:

- the server generates one;
- the response returns the same value; and
- the structured request record contains that exact value.

For a valid caller-provided value, response/log preserve it exactly.

For empty, oversized, invalid-character or malformed caller values:

- the unsafe value is not trusted or truncated into acceptance; and
- a fresh server value is generated.

Request-ID propagation must be tested on at least:

```text
200
401
403 or 404
429
500
```

application-controlled responses.

# 4. Route-template logging and cardinality acceptance

A request to a concrete resource path such as:

```text
/api/v1/review-cases/<real-uuid>
```

must log the route template, for example:

```text
/api/v1/review-cases/{case_id}
```

not the concrete UUID path.

Two different Case IDs hitting the same route must converge on one route
metric dimension. Unknown URLs must use one bounded unmatched sentinel rather
than one series per raw path.

# 5. Identity logging acceptance

For an authenticated request, the request-completion log may contain only the
opaque:

```text
organization_id
actor_id
```

identity values.

The same record must not contain the user's display name, login name, Session
token, Cookie, password or password hash.

For an unauthenticated request, organization/actor fields are absent/null and
must not be guessed from request input.

# 6. Secret-leak negative acceptance

Use unmistakable sentinel secret values in representative calls for:

```text
password
current_password
new_password
Session Cookie
Authorization header
request JSON/query input
```

Capture production structured logs.

None of the sentinel values may appear.

At minimum cover:

```text
successful login
failed admitted login
throttled login
password-change rejection
authenticated GET
404/validation failure
controlled unhandled test exception
```

Production request telemetry must not serialize raw request/response bodies or
arbitrary exception text.

# 7. Structured log schema acceptance

Every request-completion JSON record has a stable shape including:

```text
timestamp
level
event
request_id
method
route
status_code
latency_ms
organization_id
actor_id
error_class
```

`latency_ms` is numeric and non-negative. Tests parse JSON records rather than
string-match hand-formatted output.

# 8. HTTP metrics acceptance

After controlled requests:

```text
easyaudit_http_requests_total
```

and request-duration observations change exactly as expected.

Dimensions are restricted to bounded values such as method, route template and
status class/code.

Tests prove no metric series contains:

```text
request_id
org_id
actor_id
raw URL
Case/Finding/Action UUID
login name
session ID
```

# 9. Authentication metrics acceptance

Exercise:

```text
successful login
invalid admitted login
throttled login
```

and verify the three bounded outcomes are independently observable with no
account identity label.

# 10. Database pool acceptance

Using an isolated Engine configured with:

```text
pool_size = 1
max_overflow = 0
```

hold the only connection and attempt a second checkout.

The second checkout must fail within configured `pool_timeout` and must not
open an overflow connection.

Production Engine configuration retains `pool_pre_ping=true`, the configured
`pool_size` and `max_overflow=0`.

Settings outside reviewed bounds must fail validation rather than silently
create an unbounded pool.

# 11. PostgreSQL timeout configuration acceptance

On an application Engine connection execute:

```text
SHOW statement_timeout
SHOW lock_timeout
SHOW idle_in_transaction_session_timeout
```

and prove the values match application configuration.

The values must be applied centrally by Engine/connection configuration, not by
a particular repository remembering to issue a `SET` statement.

# 12. Statement timeout behavior

With a low test-only `statement_timeout`, execute a real PostgreSQL statement
that exceeds the budget.

PostgreSQL cancels it, the application request/transaction fails safely and
cleanup rolls the Session back.

A bounded timeout/error class is observable without logging SQL parameters or
business secrets.

Production default remains 15 seconds unless the Gate is explicitly revised.

# 13. Lock timeout behavior

Using two independent real PostgreSQL transactions:

1. transaction A holds a conflicting lock;
2. transaction B attempts the conflicting operation;
3. B exceeds the low test-configured `lock_timeout`.

B must fail within the configured bound rather than wait indefinitely and must
rollback safely. A remains authoritative.

Production default remains 3 seconds unless explicitly revised.

# 14. Idle-in-transaction timeout behavior

Using a low test-only `idle_in_transaction_session_timeout`:

- `SHOW idle_in_transaction_session_timeout` matches configuration; and
- a real connection left idle in a transaction is terminated/invalidated by
  PostgreSQL within the expected bound.

Normal Session/pool cleanup must discard or invalidate the failed connection
rather than return it as healthy state.

Production default remains 60 seconds unless explicitly revised.

# 15. Database budget regression

Full existing PostgreSQL tests must pass under the production-style bounded
Engine configuration.

A budget that breaks valid existing Review Core concurrency behavior is not
accepted merely because timeout tests pass; any increase must be explicitly
justified in Final Review.

# 16. Login admission occurs before Argon2/audit

Using an injectable/fake monotonic clock and spies, exhaust the login admission
budget.

For a throttled request prove:

```text
AuthenticationService.login is not invoked
password verifier count does not increase
credential repository is not called
AuthSession count does not increase
PlatformAuditEvent count does not increase
HTTP response = 429
Retry-After is present
```

Returning 429 only after Argon2 has already executed is a failure.

# 17. Known versus unknown login equivalence

Run equivalent admission sequences against:

```text
real login name + wrong password
unknown login name + arbitrary password
```

For equivalent limiter state both have the same admission threshold, generic
401/429 class, Retry-After behavior and operational metric class.

The limiter must never query the database to determine account existence before
admission. Existing dummy-hash behavior remains exercised for admitted unknown
users.

# 18. Global login budget acceptance

Use many distinct submitted login names/source keys to avoid exhausting one
per-key bucket.

The global bucket must still cap actual AuthenticationService/password
verification invocations. Random usernames must not bypass the CPU/write
budget.

# 19. Login limiter concurrency acceptance

Concurrent request threads consume the final available tokens.

The implementation must not admit more verification operations than the
configured concurrent budget because of a race. The limiter is thread-safe for
FastAPI synchronous execution.

# 20. Limiter memory bound acceptance

Generate more unique submitted login/source keys than the configured state
capacity.

The limiter retains a bounded number of entries through TTL/LRU or equivalent
eviction. Raw submitted login values do not appear in eviction/debug telemetry.

# 21. Login audit behavior acceptance

For admitted invalid credentials, the existing generic invalid-credential
response and expected `auth.login_failed` audit fact remain.

For a throttled request, zero `auth.login_failed` event is appended for that
rejected request and only the operational throttled metric/log changes.

Successful admitted login retains existing AuthSession/audit behavior.

# 22. Session touch no-write window

Create/authenticate a Session with:

```text
last_seen_at = T0
```

Perform authenticated reads at:

```text
T0 + 1 minute
T0 + 5 minutes
T0 + 9 minutes 59 seconds
T0 + exactly 10 minutes
```

For all of them prove:

```text
zero last_seen_at UPDATE statements
last_seen_at remains T0
```

It is not sufficient merely to observe unchanged final row data; the fast path
must avoid issuing the UPDATE.

# 23. Session touch stale threshold

At:

```text
T0 + 10 minutes + epsilon
```

one conditional UPDATE may succeed and `last_seen_at` advances.

No Review Activity or PlatformAudit event is created by ordinary touch.

# 24. Session touch PostgreSQL CAS concurrency

Use two or more concurrent real PostgreSQL Sessions after the threshold. All
begin from the same stale `last_seen_at`.

Acceptance requires:

```text
one effective row update
other CAS writers converge safely
last_seen_at never moves backwards
Session remains valid
```

A service-only `if last_seen < ...` check without the stale predicate in the
SQL UPDATE is No-Go.

# 25. Revoked/expired Session touch acceptance

A revoked or expired Session must never have `last_seen_at` revived by the
conditional touch. Existing authentication rejection semantics remain
unchanged.

# 26. Session touch query-amplification acceptance

The successful CAS path must not perform an otherwise unused follow-up Session
reload merely because the repository method historically returned a domain
object. A focused query-count assertion should prove the narrowed write path.

# 27. Top-level React ErrorBoundary acceptance

A component deliberately throws during render beneath the application root.

Acceptance requires:

- root ErrorBoundary catches the failure;
- a generic fallback renders instead of a white/empty surface;
- fallback offers reload/retry;
- raw stack trace is absent; and
- a secret-like injected `Error.message` is not rendered.

# 28. Route-level ErrorBoundary acceptance

Cause a representative business route such as Workbench to throw during
render.

Acceptance requires:

```text
Product header remains
navigation remains
route fallback is visible
another route remains reachable
```

At least one navigation/retry test proves the route boundary resets rather than
permanently poisoning the SPA.

# 29. API default timeout acceptance

Use fake timers or deterministic mocked fetch that never resolves.

An ordinary API request with no explicit timeout is aborted at the shared
15-second default and rejects with a deterministic timeout classification.
Tests must not actually sleep for 15 seconds.

# 30. Caller cancellation acceptance

If a caller supplies its own cancellation signal and cancels the request, the
client must not misclassify that cancellation as a retryable timeout. No retry
is issued for caller cancellation.

# 31. Safe GET retry acceptance

For each permitted transient failure:

```text
transport/network failure
client timeout
502
503
504
```

GET performs at most:

```text
initial attempt + one retry
```

and never a third request. Retry uses bounded backoff/jitter.

# 32. Non-retryable GET acceptance

For:

```text
401
403
404
409
422
429
500
```

the shared client makes exactly one GET request.

A 401 continues to invoke the existing Session unauthorized handler and is not
hidden behind retry.

# 33. Mutation no-retry acceptance

For every mutation-class method supported by the shared client:

```text
POST
PUT
PATCH
DELETE
```

simulate transport failure, timeout, 502, 503 and 504 and prove exactly one
network attempt.

At minimum explicitly cover POST login and an existing ReviewPlan/ReviewCase or
other business mutation.

Generic mutation auto-retry is a P1 failure until a later exact M6.2
idempotency contract authorizes a specific replay.

# 34. Python lock acceptance

The candidate contains committed:

```text
uv.lock
```

covering the resolved runtime and canonical development dependency sets.

The exact `uv` tool version is pinned in canonical CI/build configuration.

# 35. Lock freshness acceptance

Canonical CI performs a lock-consistency/frozen check.

If `pyproject.toml` dependency metadata changes without a matching lock update,
CI fails. A developer must not be able to change a dependency range and obtain
a green build from a stale lock.

# 36. CI installation from lock

Backend CI is created/synchronized from the committed lock. Ruff, mypy, pytest,
Alembic and architecture/OpenAPI checks execute in that locked environment.

The unrestricted `python -m pip install -e ".[dev]"` resolver is no longer the
authoritative source of resolved backend versions.

# 37. Docker installation from lock

A clean Docker build installs the production Python dependency set from the
same committed lock and does not independently re-resolve all `pyproject.toml`
ranges.

Frontend continues to use:

```text
web/package-lock.json
npm ci
```

without a package-manager migration.

# 38. No-migration proof

Candidate diff contains no new or changed file under:

```text
alembic/versions/
```

Normal CI still runs `alembic upgrade head` and existing migration tests remain
green.

# 39. Review Core freeze proof

Candidate/control diff proves no production change under:

```text
src/easyaudit_next/review_core/**
src/easyaudit_next/scenarios/**
```

and architecture regression proves operational modules do not become Review
Core dependencies.

Existing Process Review, Compliance Review, authorization, concurrency,
notifications, management, reminder/nudge and Product/browser regression remain
green.

# 40. Required automated evidence

Before Implementation Review, focused automated coverage must exist for:

```text
health/live and health/ready
Alembic mismatch
Request-ID validation/propagation
structured-log schema
secret-log negative cases
route-template logging and bounded metrics
DB pool exhaustion
statement timeout
lock timeout
idle transaction timeout
login per-key/global throttling
no-Argon2/no-audit throttle path
limiter concurrency/memory bound
10-minute Session touch fast path
Session touch real-PostgreSQL CAS race
top-level ErrorBoundary
route-level ErrorBoundary
API timeout
GET retry
mutation no-retry
lock freshness
```

Full canonical evidence additionally requires:

```text
Ruff
mypy
architecture check
OpenAPI check
Alembic upgrade
full real-PostgreSQL pytest
frontend typecheck/lint/unit tests/build
browser foundation
real PostgreSQL + FastAPI + React browser acceptance
Docker build from lock
Review Bundle
exact-head GitHub Actions
```

# 41. Manual operational evidence

Final Review should capture one human-readable correlation sample:

```text
request
  -> X-Request-ID response header
  -> matching JSON request log
  -> matching route metric increment
```

and one readiness-failure sample:

```text
FastAPI process alive
DB unavailable or intentionally schema-mismatched
/health/live = 200
/health/ready = 503
```

These supplement automated tests; they do not replace them.

# 42. P1 failure conditions

Any of the following is at least P1 for this slice:

- `/health/ready` returns 200 with unavailable PostgreSQL;
- `/health/ready` returns 200 with mismatched Alembic heads;
- readiness performs migrations;
- liveness depends on PostgreSQL;
- password/cookie/token appears in production telemetry;
- raw resource IDs or raw paths are metric route labels;
- DB pool can exceed the reviewed connection budget;
- statement/lock waits remain unbounded;
- throttled login still performs Argon2/credential lookup;
- throttled login still appends one PlatformAudit row per request;
- rate limiting reveals account existence;
- random login names create unbounded limiter memory;
- authenticated reads continue updating `last_seen_at` within 10 minutes;
- Session stale protection exists only in Python and not the SQL UPDATE;
- concurrent stale touches repeatedly update or regress `last_seen_at`;
- a route render error collapses the whole SPA without required containment;
- GET retry is unbounded;
- any mutation receives generic automatic retry;
- CI or Docker ignores the committed Python lock; or
- M6-Ops changes Review Core/Scenario business semantics.

# 43. Go / No-Go

## Go

M6-Ops may pass Final Review only when:

```text
P0 = 0
P1 = 0
P2 = 0
```

and all of the following hold:

- liveness/readiness behavior is proven against real PostgreSQL outage and
  migration mismatch;
- Request-ID correlation works across response/logging;
- production telemetry passes secret-leak negative tests;
- route/metric cardinality is bounded;
- database pool and timeout budgets are active and behaviorally proven;
- login admission bounds actual Argon2 and PlatformAudit work;
- account-enumeration resistance is preserved;
- Session writes are throttled by the exact 10-minute fast-path plus SQL CAS;
- frontend top-level and route-level failures are contained;
- ordinary API calls have bounded timeout;
- only safe GET gets at most one automatic retry;
- mutations receive zero automatic retries;
- `uv.lock` is authoritative for CI and Docker dependency resolution;
- no migration or Review Core/Scenario production change exists;
- full backend/frontend/browser regression is green;
- Review Bundle is current;
- candidate head is fixed; and
- exact-head GitHub Actions is green.

## No-Go

M6-Ops is No-Go if required proof depends on:

```text
static /health readiness
mock-only database evidence
sleep-based login backoff
new persistent rate-limit state without Gate revision
raw credential/request logging
unbounded metric labels
unbounded DB pool/timeout behavior
service-only Session staleness check
blind mutation retry
stale dependency lock
floating dependency resolution
Review Core or Scenario modification
unreviewed migration
skipped real PostgreSQL/browser evidence
stale Review Bundle
non-exact candidate CI
```

# 44. Known controlled-pilot limitations after M6-Ops

Passing M6-Ops does not mean the entire M6 program is rollout-ready.

The following remain intentionally unresolved until their own Gates:

```text
M6.2  creation idempotency / unknown-result recovery
M6.3  server-controlled Evidence binary storage/download
M6.4  real daily scheduled reminder execution
M6.5  bounded authorized exports
M6-RC final joint recovery qualification
```

The application-level login limiter is process-local and qualifies only the
bounded reviewed API topology. Horizontal API expansion requires requalification
or shared enforcement.

M6-Ops does not claim full distributed tracing, centralized log retention,
SIEM integration, general autoscaling or data-retention lifecycle governance.
Data lifecycle remains M7.
