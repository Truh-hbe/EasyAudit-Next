# M6-Ops Operational Readiness Foundation

## Gate status

This document defines the Architecture Gate for:

```text
M6-Ops — Operational Readiness Foundation
```

M6-Ops is a cross-cutting production-engineering slice over the already
validated EasyAudit-Next Modular Monolith. It does not create a new business
capability and it does not change Review truth.

The roadmap dependency remains:

```text
M6.1a
  ->
M6.1b
  ->
M6-Ops
  ->
M6.2
```

This Gate may be drafted and reviewed now. Executable implementation must not
bypass the reviewed M6 predecessor conditions. This Gate does not authorize
merge, deployment, secret access, restore rehearsal, real pilot traffic or any
later M6 slice.

## Goal

Close the minimum operational-readiness gaps required before the existing
application can safely carry bounded controlled-pilot traffic.

M6-Ops must make the current application:

```text
probeable
+
correlatable
+
resource-bounded
+
abuse-resistant
+
frontend-failure-tolerant
+
dependency-reproducible
```

while preserving the existing architecture:

```text
React
  |
  v
FastAPI Modular Monolith
  |
  v
request-scoped synchronous SQLAlchemy Session
  |
  v
PostgreSQL 17
```

M6-Ops adds operational control around that architecture. It does not replace
it.

## Existing gaps closed by this slice

The current baseline intentionally retains several pilot-era simplifications:

- `/health` is a static process response and does not prove database/schema
  readiness;
- the SQLAlchemy Engine uses `pool_pre_ping=True` but has no explicit pool or
  PostgreSQL statement/lock/idle-transaction budget;
- every authenticated request reaches the Session touch path;
- `auth_sessions.last_seen_at` can be updated on every successful touch;
- the login path performs expensive Argon2 verification and persists
  append-only authentication audit facts without an admission budget;
- the shared React API client has no default timeout or narrowly bounded retry
  policy;
- the React root and business routes have no ErrorBoundary containment; and
- backend dependencies are range-declared in `pyproject.toml` and canonical
  CI/container builds can re-resolve them rather than install one committed
  resolved dependency set.

M6-Ops closes only these operational gaps.

# 1. Non-negotiable architecture boundaries

## 1.1 Review Core and Scenario semantics are frozen

M6-Ops must not change Review Core domain models or Scenario behavior.

The implementation must not alter:

```text
ReviewPlan
ReviewCase
Finding
ActionItem
Submission
Activity
CaseMember / FindingParticipant / ActionAssignee semantics
Scenario lifecycle
Scenario permissions
Scenario role definitions
collaboration recipient semantics
deadline semantics
Review Core locking/concurrency protocols
organization-scoped business authorization
```

No health, telemetry, rate-limit or runtime concern may be represented as a
Review aggregate or Review Activity.

Production changes under `src/easyaudit_next/review_core/**` or
`src/easyaudit_next/scenarios/**` are forbidden for this slice unless the Gate
is explicitly reopened.

## 1.2 No database migration

M6-Ops requires no schema change.

Forbidden additions include:

```text
operational metrics tables
request-log tables
login-attempt tables
rate-limit tables
session schema changes
Review Core migrations
Scenario migrations
```

If implementation discovers that a migration is required, stop implementation
and reopen this Gate.

## 1.3 Audit facts and operational telemetry remain separate

`PlatformAuditEvent` remains append-only security/administrative audit history.
Structured logs and metrics are operational telemetry.

An admitted invalid login may continue to create the existing
`auth.login_failed` audit fact. A request rejected by the M6-Ops login admission
limiter before credential verification must not create one PlatformAudit row
per rejected request merely for telemetry. It is represented by operational
log/metric evidence instead.

## 1.4 No infrastructure expansion without evidence

M6-Ops does not require:

```text
Redis
Kafka
RabbitMQ
Celery
service mesh
distributed tracing platform
new microservice
```

The controlled pilot remains a bounded Modular Monolith.

# 2. Health architecture

The ambiguous legacy health behavior is replaced operationally by two explicit
probes.

## 2.1 `GET /health/live`

Purpose:

> Is this FastAPI process alive enough to accept an HTTP request?

The liveness handler must:

- perform no database query or checkout;
- perform no Alembic query;
- require no authenticated Session;
- perform no external I/O;
- perform no business authorization;
- create no PlatformAudit/Activity/Notification/business record; and
- return quickly even if PostgreSQL is unavailable.

Success is HTTP 200 with a minimal bounded response such as:

```json
{"status":"alive"}
```

A PostgreSQL outage must not turn liveness into failure.

## 2.2 `GET /health/ready`

Purpose:

> Can this application instance safely serve requests against the database
> schema shipped with this exact release?

Readiness is successful only if both are true:

```text
PostgreSQL connectivity
AND
database Alembic head set == code Alembic head set
```

Required sequence:

```text
acquire bounded application DB connection
  -> SELECT 1
  -> read current DB Alembic heads
  -> read expected code Alembic heads
  -> exact set equality
```

The implementation must resolve the expected head set from the migration
scripts shipped with the release and compare it with the connected database
through Alembic APIs. Do not hard-code one revision string or use an ordinal
`>=` comparison.

Readiness must fail closed for:

```text
DB unavailable
pool checkout unavailable
database behind code
database ahead of code
diverged/unexpected migration head
empty migration state where a migrated DB is required
```

Failure is HTTP 503 with a bounded non-secret reason. It must not expose
DATABASE_URL, credentials, raw exception text, stack traces or SQL.

`/health/ready` is read-only. It must never run `alembic upgrade`, repair schema
state or mutate business data.

## 2.3 Legacy `/health`

The existing `/health` route may remain temporarily as a compatibility-only
liveness alias. It is not authoritative rollout readiness.

Canonical CI/deployment/browser startup readiness must move to:

```text
/health/ready
```

# 3. Request correlation

Every HTTP request must receive exactly one server-accepted Request ID.

Header:

```text
X-Request-ID
```

A caller-provided value may be preserved only when it satisfies a strict
bounded format such as:

```text
^[A-Za-z0-9._:-]{1,64}$
```

Absent, oversized or malformed values are discarded and replaced with a fresh
collision-resistant opaque server identifier. Do not truncate and accept an
unsafe value.

Every application-controlled response, including 2xx, 4xx, 429 and 5xx, must
carry the accepted/generated `X-Request-ID`.

After authentication succeeds, request-local observability context may bind
only opaque `organization_id` and `actor_user_id`. It must not bind display
name, login name, password, password hash, raw token, Cookie or arbitrary
business payload. Observability context must never become an authorization
source.

# 4. Structured logging

Production request logs must be machine-parseable JSON.

Minimum request-completion fields:

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

Fields may be null when unavailable.

`route` means the matched route template, for example:

```text
/api/v1/review-cases/{case_id}
```

not a concrete resource URL containing UUIDs. Unmatched routes use one bounded
sentinel such as `__unmatched__`.

Latency must use a monotonic clock.

Production request telemetry must never log:

```text
password/current_password/new_password/temporary password
password hash
Cookie header or Set-Cookie value
session token
Authorization bearer value
private key or secret value
DATABASE_URL with credentials
request body or response body
raw Evidence content
raw query string by default
```

Unexpected failures may record a bounded `error_class`. The authoritative
request record must not blindly serialize `str(exception)`, `repr(exception)`
or arbitrary traceback values.

The qualified runtime should avoid a second unstructured Uvicorn access log
when it would duplicate requests or expose raw paths/query data. The custom
structured request record is authoritative.

# 5. Operational metrics

M6-Ops establishes a bounded in-process metrics registry and scrapeable
operational surface, preferably:

```text
GET /metrics
```

It is an operational endpoint, not a Product API, should be excluded from the
Product OpenAPI contract, and remains inside the approved private operational
boundary.

At minimum expose:

```text
easyaudit_http_requests_total
easyaudit_http_request_duration_seconds
```

with bounded labels such as method, route template and status class/code.

Forbidden metric labels include:

```text
request_id
organization_id
actor_id
case_id/finding_id/action_item_id
session_id
login_name
raw path
```

Authentication metrics must distinguish at least:

```text
success
invalid
throttled
```

without account identity labels.

Database observability must expose enough bounded information to diagnose:

```text
configured pool size
checked-out connections
overflow
pool checkout timeout count
statement timeout
lock timeout
deadlock
other bounded DB failure class
```

M6.3 and M6.4 may later add Evidence/scheduler metrics through this common
facility. M6-Ops must not create fake future business models just to populate
those metrics now.

# 6. Database connection and timeout budget

The existing synchronous SQLAlchemy Session and one-request transaction model
remain authoritative.

`src/easyaudit_next/infrastructure/database.py` and validated settings must
make resource limits explicit.

Controlled-pilot defaults:

```text
pool_size                           = 5
max_overflow                        = 0
pool_timeout                        = 5 seconds
statement_timeout                   = 15 seconds
lock_timeout                        = 3 seconds
idle_in_transaction_session_timeout = 60 seconds
pool_pre_ping                       = true
```

Suggested validated settings bounds:

```text
database_pool_size:                    1..20, default 5
database_pool_timeout_seconds:         1..30, default 5
database_statement_timeout_ms:      1000..120000, default 15000
database_lock_timeout_ms:             100..30000, default 3000
database_idle_transaction_timeout_ms: 5000..300000, default 60000
```

`max_overflow=0` is fixed for the controlled pilot unless a later Gate expands
the connection budget. Configuration must reject non-positive budgets and
`lock_timeout >= statement_timeout`.

Every application connection must receive the PostgreSQL session timeout
settings centrally through Engine/connection configuration before ordinary
business statements execute. Individual repositories must not be responsible
for remembering `SET` statements.

The qualified deployment must keep:

```text
sum(api processes * pool_size + other explicitly qualified application pools)
```

inside the approved PostgreSQL connection budget with reserve for migration and
controlled administration.

# 7. Login abuse resistance and write amplification

The login endpoint performs intentionally expensive password verification and
persists audit facts. Admission protection must execute before credential
lookup, Argon2/dummy Argon2 verification and PlatformAudit insertion for a
throttled request.

Rate limiting must not depend on whether the submitted login exists. Known and
unknown users follow the same admission algorithm.

A bounded process-local token-bucket implementation is sufficient for the
single/fixed pilot API topology; no Redis or persistence model is required.

The pilot limiter has two independent budgets:

```text
global verification bucket
+
per submitted-login/source bucket
```

Recommended initial values:

```text
global: capacity 20, refill 1 token/second
per login/source: capacity 5, refill 1 token/12 seconds
```

Each admitted attempt consumes capacity regardless of eventual success or
failure.

Per-key state must use an opaque fingerprint rather than exposing raw login
names in logs/metrics. State must be thread-safe, monotonic-clock based,
bounded in entry count and TTL/LRU evicted. Random usernames must not create an
unbounded dictionary.

The limiter must never call `sleep()` to implement backoff.

When denied:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: <bounded seconds>
```

The response is generic and reveals no account existence.

A throttled request must perform:

```text
zero password verification
zero AuthSession creation
zero PlatformAuditEvent creation
```

and increment only operational throttling telemetry.

Process-local rate limiting qualifies only the bounded reviewed API topology.
If later deployment adds independently reachable replicas/processes, aggregate
admission capacity must be requalified or shared/gateway enforcement introduced
through a later Gate.

# 8. Session `last_seen_at` write throttling

Session validity semantics remain unchanged. Authentication still rejects
unknown, revoked, expired or inactive-user sessions.

M6-Ops changes only how often an already valid Session updates
`last_seen_at`.

Fixed pilot interval:

```text
10 minutes
```

A row may update only when:

```text
now - persisted last_seen_at > 10 minutes
```

Exactly ten minutes is not stale.

Because authentication already loaded the authoritative Session row, the
service should first use that value as a fast path. Inside the interval, no
UPDATE statement is issued.

Once the coarse value is stale, the repository must execute one atomic
conditional update equivalent to:

```sql
UPDATE auth_sessions
SET last_seen_at = :now
WHERE id = :session_id
  AND token_hash = :expected_token_hash
  AND revoked_at IS NULL
  AND expires_at > :now
  AND last_seen_at < :stale_before;
```

where `stale_before = now - 10 minutes`.

The database stale predicate is mandatory. A Python-only check is insufficient
because concurrent requests may all observe the same stale Session.

Concurrent stale requests must converge so one request may update and the
others observe zero-row CAS results. `last_seen_at` must never move backwards.
A successful touch does not require an otherwise unused follow-up SELECT; a
boolean/row-count result is enough.

# 9. Frontend failure containment

React must gain both application-level and route-level ErrorBoundaries without
rewriting the router or state-management architecture.

## 9.1 Top-level boundary

The application root must contain failures beneath Router/SessionProvider/App.
The fallback must:

- render without business API data;
- show a generic failure message;
- offer a safe reload/retry action;
- not render raw stack traces; and
- not render arbitrary `Error.message` in production.

## 9.2 Route-level boundaries

Substantial business routes must be independently contained, including at
minimum:

```text
Workbench
ReviewCase collection/detail
ReviewPlan/ReviewCase creation
Finding detail
Action detail
Notifications
Management
Admin
```

A route render failure should preserve the authenticated Product Shell where
possible: header/navigation remain usable and another route can be reached.
Navigating away or explicitly retrying must reset the failed route boundary.

# 10. API client timeout

Every ordinary JSON API request has a bounded shared default timeout:

```text
15 seconds per attempt
```

The shared API client owns this behavior. Feature pages must not each reinvent
timeout logic.

Timeout must cancel the browser request using AbortController/AbortSignal or an
equivalent mechanism. Caller-initiated cancellation and internal timeout must
remain distinguishable so component unmount/cancel is not misreported as a
server timeout.

M6.3 may define a different streaming upload/download timeout contract through
its own Gate.

# 11. Safe retry contract

Generic mutation retry remains forbidden.

Automatic retry is permitted only for `GET`.

A GET may retry once (maximum two attempts total) for:

```text
transport/network failure
client timeout
HTTP 502
HTTP 503
HTTP 504
```

A GET must not automatically retry:

```text
401
403
404
409
422
429
500
caller-initiated abort
```

Retry uses short bounded backoff/jitter and no unbounded loop.

The existing authenticated-session 401 handler remains authoritative and a 401
is never hidden behind retry.

No automatic retry for:

```text
POST
PUT
PATCH
DELETE
```

This includes login/logout/password change, ReviewPlan/ReviewCase creation,
Finding/Action mutation, notifications, reminder/nudge and administration.
M6.2 may later authorize replay only for the exact operations protected by its
idempotency contract.

# 12. Python dependency lock

M6-Ops introduces one committed Python dependency lock:

```text
uv.lock
```

`pyproject.toml` remains the human-maintained dependency-intent manifest.
`uv.lock` becomes the exact resolved dependency identity used by canonical CI
and container builds.

The `uv` tool itself must be pinned to one exact reviewed version in canonical
CI/build configuration.

Canonical backend CI must:

```text
read pyproject.toml
read uv.lock
verify lock is current
sync/install from the committed lock
fail if metadata and lock disagree
```

The unrestricted `pip install -e ".[dev]"` resolver path must no longer be the
authoritative source of backend versions.

The production Docker build must install the backend dependency set from the
same committed lock rather than independently re-resolving range constraints.

The existing frontend contract remains:

```text
web/package-lock.json
npm ci
```

No second frontend package manager is introduced.

`uv.lock` proves the resolved Python dependency set. It does not by itself
claim byte-for-byte reproducible container images; immutable base/runtime image
identity and final release digests remain part of the wider M6 release/recovery
evidence chain.

# 13. Proposed implementation surface

A narrow implementation may add an operational module such as:

```text
src/easyaudit_next/operations/
  __init__.py
  health.py
  request_context.py
  logging.py
  metrics.py
```

and a narrow login admission component under Platform application code.

Expected existing production files that may require modification include:

```text
src/easyaudit_next/main.py
src/easyaudit_next/api/router.py
src/easyaudit_next/api/dependencies.py
src/easyaudit_next/infrastructure/database.py
src/easyaudit_next/platform/settings.py
src/easyaudit_next/platform/application/authentication.py
src/easyaudit_next/platform/persistence/repositories.py
web/src/main.tsx
web/src/app/shell/ProductShell.tsx
web/src/app/errors/**
web/src/api/client.ts
pyproject.toml
uv.lock
Dockerfile
compose.yaml
.github/workflows/ci.yml
scripts/check_architecture.py
```

This list is a Gate proposal, not permission for unrelated edits.

Operational infrastructure may depend on Settings, SQLAlchemy Engine,
FastAPI/ASGI, logging and the metrics library. It must not depend on Review
Core domain models, Scenario implementations, Workbench/Management business
queries, Notification business semantics or reminder recipient policy. Review
Core must never import the operational layer.

# 14. CI/runtime cutover

Canonical real-browser backend startup changes conceptually from:

```text
start backend -> poll /health
```

to:

```text
migrate DB -> start backend -> poll /health/ready -> run browser acceptance
```

This proves a static process response is not mistaken for rollout readiness.

# 15. Explicit non-goals

M6-Ops does not implement:

```text
M6.2 creation idempotency or unknown-result reconciliation
M6.3 Evidence binary storage
M6.4 scheduler cadence
M6.5 export
M6-RC recovery rehearsal
data-retention lifecycle/erasure governance
session cleanup scheduler
MFA/SSO
distributed rate limiting
distributed tracing
horizontal autoscaling
central log platform
business analytics
```

Data lifecycle/retention governance remains M7.

# 16. Review evidence requirements

Implementation Review requires focused automated evidence for every invariant
in `m6-ops-acceptance.md`, plus full regression.

Final Review requires at minimum:

```text
Ruff
mypy
architecture check
OpenAPI check
Alembic upgrade from the normal baseline
real PostgreSQL pytest
frontend typecheck/lint/unit/build
browser foundation acceptance
real PostgreSQL + FastAPI + React browser acceptance
Python lock freshness check
Docker build from committed lock
current Review Bundle
exact-head GitHub Actions success
```

No local-only result is sufficient for Final Review.

# 17. Gate lifecycle

```text
GATE_DRAFT
  -> GATE_REVIEW
  -> IMPLEMENTATION
  -> IMPLEMENTATION_REVIEW
  -> FINAL_REVIEW
  -> MERGE_AUTHORIZED
  -> MERGED
```

Moving from Gate Review to executable implementation additionally requires the
roadmap predecessor condition to be satisfied.

Final Review requires:

```text
P0 = 0
P1 = 0
P2 = 0
fixed candidate head
clean candidate/control/working-tree evidence
current Review Bundle
exact-head CI green
```

Merge still requires explicit authorization under the project development
workflow.
