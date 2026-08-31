# 实施路线

This roadmap is rebaselined after the M5 controlled-pilot hardening, the
completed M6.0 rollout-readiness planning work, and the subsequent architecture
and engineering health review.

Current baseline:

```text
main@9d3daaa941548066b65877a5aa434fcdbb46c745
```

M6.0 controlled-pilot rollout readiness is complete as a planning and
governance slice. The forward M6 sequence below refines the implementation and
qualification order after the architecture health review.

This roadmap revision does not retroactively alter completed M6.0 review
evidence. Each active or future executable slice must adopt the revised
dependency order through its own reviewed Gate before work outside its existing
scope is authorized.

A roadmap entry never authorizes implementation, deployment, secret access,
restore rehearsal, real pilot traffic or merge by itself.

## Completed — M0 Bootstrap

* Python / FastAPI / SQLAlchemy synchronous Session / psycopg 3 / PostgreSQL / Alembic engineering baseline.
* Corrected core concepts, relationship invariants and historical ScenarioVersion addressing.
* Cross-Scenario ReviewPlan, cross-department ActionAssignee and strong-FK persistence rules.
* OpenAPI, containers, automated tests, architecture guards and CI.

## Completed — M1 Platform Foundation

* Organization, Department, User, LocalCredential and server Session.
* Platform role and business relationship separation.
* Persistent ScenarioVersion, Review Core aggregates and append-only Activity.
* Organization-scoped relationship and authorization invariants.

## Completed — M2 Process Review

* `process_review@1` became the first real Scenario over generic Review Core.
* Planning → Case → Finding → rectification Action → Submission → verification → closure is executable end to end.
* Exact Scenario policy owns workflow, authorization, input validation and role specifications.

## Completed — M3 Collaboration & Management

M3 extended the working business core without moving business truth into a second model:

```text
M3.1  Workbench & Query Foundation
M3.2  Persistent Notifications
M3.3  Management Progress Queries
M3.4  Reminder / Nudge
```

The stage established personal work projection, persistent delivery history,
management read-side facts and Scenario-owned collaboration recipient
semantics.

## Completed — M3.5 Product Surface

M3.5 composed M2 + M3 into the first coherent React product while keeping the
backend authoritative for authorization, lifecycle, deadline, recipient and
provenance truth.

```text
M3.5.1  Product shell + authentication + navigation
M3.5.2  Workbench + ReviewCase surface
M3.5.3  Finding / Action collaboration surface
M3.5.4  Notification + Management + Reminder actions
M3.5.5  Product acceptance / responsive / final polish
```

M3.5 Final Acceptance passed a real PostgreSQL + FastAPI multi-user Product
journey and responsive/accessibility acceptance.

## Completed — M4 Second Scenario Validation

M4 proved that EasyAudit-Next is a reusable audit platform rather than a
Process Review application with unused abstractions.

The exact second Scenario is:

```text
compliance_review@1
```

Its material behavior differs from `process_review@1`:

```text
finding_type = observation
OPEN --accept_observation--> CLOSED
```

without manufacturing an ActionItem or rectification Submission. Compliance
`nonconformity` continues to use the existing rectification family with
persisted responsibility relationships.

M4 preserved the generic platform boundaries:

* both Scenarios use the existing ReviewPlan / ReviewCase / Finding / ActionItem / Submission / Activity model;
* generic HTTP APIs and M3 Workbench / Management / Notification / Reminder-Nudge services are reused rather than copied;
* Review Core and generic application services contain no Scenario-identity business branches;
* exact `(scenario_key, scenario_version)` backend policy and frontend UI adapter resolution remain fail-closed;
* authenticated Users and Departments remain collaboration identities;
* Process Review behavior remains unchanged; and
* the Product Surface delegates Scenario-specific Finding interactions through the centralized exact-version adapter seam.

M4.1 also exposed and closed the narrow generic direct-Finding-transition
abstraction gap. Real PostgreSQL acceptance proved organization isolation and
Case-close versus observation-close safety without a new lock architecture.
Real FastAPI + Playwright acceptance exercised both Scenarios in the same
product build/database.

M4 was intentionally not pre-numbered beyond M4.1. Because the merged M4.1
executable implementation satisfied the complete frozen M4 acceptance
objective, no artificial `M4.2` is required solely for numbering continuity.

## Completed — M5 Controlled Pilot

M5.1–M5.4 delivered the controlled-pilot product capabilities while preserving
backend authority, exact Scenario policy and organization isolation:

```text
M5.1  Review Catalog and Scenario Readiness
M5.2  Plan-first Planning Surface
M5.3  Case Team Planning
M5.4  Minimal Pilot Administration
```

M5.1 established the exact catalog/publication readiness; M5.2 delivered the
plan-first planning surface and creation checkpoint; M5.3 delivered Case team
planning and collaboration administration; and M5.4 delivered minimal pilot
administration and credential recovery.

M5.5 then hardened the integrated pilot evidence. Its real PostgreSQL/API/React
proof covers clean bootstrap and exact publication, both `process_review@1`
and `compliance_review@1`, plan-first recovery, team safety, organization
isolation and administrator credential reset.

M5.5 is complete as a controlled-pilot evidence slice; it does not claim
production deployment, binary Evidence storage, recurring scheduling, export,
production observability or disaster-recovery qualification.

## Next — M6 Controlled Pilot Rollout Readiness

M6 converts the already functional controlled-pilot product into a system that
is operationally qualified for bounded real-user traffic.

The architecture health review preserves the existing Modular Monolith,
synchronous SQLAlchemy Session, request-scoped transaction, strong-FK tenant
integrity and exact Scenario policy boundaries. M6 must close production
engineering gaps around recovery, observability, ambiguous retries, binary
storage, scheduled execution and bounded export without redesigning Review
Core.

The revised dependency order is:

```text
M6.1a  Recovery contract / tooling validation (completed)
  ->
Process OMP Agent Control Plane Hardening
  ->
M6.1b  Real private-network infrastructure qualification
  ->
M6-Ops Operational Readiness Foundation
  ->
M6.2   Plan/Case idempotency + unknown-result recovery
  ->
M6.3   Evidence binary upload + authorized download
  ->
M6.4   Daily scheduled automatic reminder
  ->
M6.5   Authorized snapshot CSV/XLSX export
  ->
M6-RC  Final Release Candidate joint recovery qualification
  ->
Pre-rollout Go/No-Go
  ->
explicit user authorization for bounded rollout
  ->
bounded controlled rollout
  ->
five-day soak
  ->
M6 Program Final Review
```

A later item cannot be implemented merely because it appears here. Every
executable source-changing slice requires its own reviewed Gate, scope,
implementation review, exact-head GitHub evidence and Final Review.

### M6.1a — Recovery contract / tooling validation

M6.1a establishes the machine-verifiable contract required to prove recovery
safely without claiming that a real environment has already been qualified.

Its scope includes:

* immutable release-set identity;
* complete API and web/gateway OCI digest identity;
* configuration revision and opaque secret-reference identity;
* joint PostgreSQL/object recovery-set schema;
* immutable recovery-attempt evidence;
* restore ordering and compatibility fields;
* RPO/RTO evidence definitions;
* rollback evidence contract;
* evidence sanitization and secret-leak rejection;
* recovery manifest validation tooling; and
* focused contract/tooling tests.

M6.1a may prove schema validity, cross-document consistency, sanitization and
hermetic fixture behavior.

It must not by itself claim:

```text
organization-trusted private HTTPS
negative public-exposure proof
real backup failure-domain separation
real clean-target restore
measured production-environment RPO/RTO
real release rollback
```

A green CI run for the recovery contract is necessary evidence, but it is not
equivalent to successful disaster-recovery qualification. M6.1a is complete on
`main`; its contract/tooling merge does not qualify a real environment.

### Process interlock — OMP Agent Control Plane Hardening

A process-integrity incident during the early M6-Ops implementation attempt
proved that conversation instructions alone are insufficient: an OMP Agent
continued after context compaction, entered Final Review with failed CI,
weakened an exact browser assertion, and raced another OMP Session in the same
working tree. The M6-Ops implementation PR is therefore parked as Draft in
`IMPLEMENTATION`; it is neither a fixed candidate nor merge-authorized.

Before further M6 product progression, the project must establish a reviewed
OMP Agent control plane with:

```text
per-turn state/preflight injection
single-writer workspace lease
phase/scope mutation guards
candidate/control/dirty-tree enforcement
independent GitHub evidence verification
connector fallback without authority expansion
single-transition prompt orchestration
Gate/CI fail-closed fallback
```

This process slice changes no Review or product truth. Its docs-only Gate and
subsequent executable tooling implementation each require independent review.
Completing it does not satisfy M6.1b and does not authorize the parked M6-Ops
implementation to enter Final Review. The product sequence resumes with M6.1b;
M6-Ops must then be rebased/requalified against the resulting `main`.

### M6.1b — Real private-network infrastructure qualification

M6.1b executes the recovery contract against an approved no-traffic private
environment.

The qualified pilot substrate contains only the minimum required runtime:

```text
approved private/VPN network
        |
organization-trusted HTTPS gateway
        |
React product + /api/v1/* same-origin proxy
        |
FastAPI
        |
PostgreSQL 17

controlled recovery utility
        |
private S3-compatible object storage
```

The gateway is the only externally reachable component. Internal API,
PostgreSQL, object-storage API and administration interfaces must not publish
host ports.

Qualification must prove, against immutable release/configuration identity:

* fresh deployment from empty disposable volumes;
* organization-trusted HTTPS;
* approved-private reachability;
* negative public-exposure evidence;
* PostgreSQL and expected Alembic-head readiness;
* separately recoverable backup failure domain;
* one jointly verifiable PostgreSQL/object recovery cut;
* restore into a distinct clean target;
* layered application/browser readiness after restore;
* controlled rollback to an immutable known-good release without restoring the database;
* preserved database/object facts after rollback; and
* measured:

```text
RPO <= 24 hours
RTO <= 4 hours
```

M6.1b remains a no-traffic qualification. It does not authorize pilot users,
Evidence application APIs or production rollout.

M6.1 establishes the recovery mechanism and infrastructure contract. Because
later M6 slices change the final application image, schema and real Evidence
boundary, its recovery proof must not be treated as the final rollout recovery
proof. M6-RC owns that final qualification.

### M6-Ops — Operational Readiness Foundation

M6-Ops closes the production-engineering gap between a correct application and
an operable application.

It must remain a cross-cutting infrastructure/application-observability slice;
it must not create a second business model, change Scenario permissions or
move Review truth out of Review Core.

The minimum scope is:

#### Structured request/application logging

Logs must support correlation without leaking credentials or business-secret
material.

Expected fields include, where applicable:

```text
request_id
route template
HTTP status
latency
error class
opaque organization/user identifiers
```

Logs must not contain:

```text
passwords
raw Session cookies/tokens
private keys
secret values
raw object-storage credentials
Evidence binary content
```

#### Liveness and readiness

Separate:

```text
/health/live
```

for process liveness from:

```text
/health/ready
```

for rollout readiness.

Readiness must at minimum verify PostgreSQL connectivity, expected schema /
Alembic compatibility and required runtime configuration. After M6.3, object
storage becomes part of application readiness where appropriate.

A static HTTP `200` alone is not sufficient production readiness evidence.

#### Operational metrics

At minimum expose or otherwise collect enough evidence to diagnose:

```text
HTTP latency / errors
database pool usage / exhaustion
database timeout / lock / deadlock signals
authentication successes / failures / throttling
scheduled reminder last attempt / last success
scheduled reminder duration / candidate count / inserted count
Evidence upload/reconciliation failures after M6.3
backup age / recovery evidence freshness
```

Full distributed tracing is not a prerequisite for the controlled pilot.

#### Database connection and transaction budgets

Production configuration must explicitly bound:

```text
application concurrency
SQLAlchemy pool size / overflow
PostgreSQL connection budget
statement timeout
lock timeout
idle transaction timeout
```

The existing synchronous Session and one-request transaction model remain the
authoritative transaction architecture.

#### Authentication abuse resistance

The pilot must add bounded protection against repeated login attempts so that
Argon2 verification and append-only authentication audit events cannot be used
as an uncontrolled CPU/database-write amplifier.

Protection must not reintroduce account enumeration.

#### Session write/lifecycle control

Authenticated reads must not cause unnecessary unbounded session-row write
amplification.

The implementation should use a bounded `last_seen_at` touch interval rather
than updating the Session row for every request, and expired/revoked Session
records require an explicit cleanup policy.

#### Release/runtime reproducibility

The pilot release must have a reproducible dependency identity sufficient to
rebuild and audit a deployed release.

At minimum the rollout process should record or generate:

```text
resolved backend dependency set
frontend lockfile identity
base/runtime image identity
release artifact digests
SBOM or equivalent dependency inventory
```

Container/runtime hardening should avoid running application services with
unnecessary privileges.

M6-Ops does not require microservices, Redis, Kafka, a service mesh or a
distributed tracing platform.

### M6.2 — Plan/Case creation idempotency and unknown-result recovery

M6.2 owns only the create operations required by the existing plan-first
workflow.

The authoritative idempotency scope must include enough identity to prevent
cross-user and cross-organization replay, including:

```text
organization
actor
operation
stable idempotency key
canonical request fingerprint
```

Required behavior:

```text
same key + same request
-> converge to the same authoritative result

same key + different request
-> fail safely

concurrent same-key requests
-> one authoritative creation
```

The idempotency fact, created ReviewPlan/ReviewCase and corresponding Activity
must converge inside the same PostgreSQL transaction boundary.

M6.2 must cover:

* concurrent identical requests;
* browser/network unknown-result ambiguity;
* safe replay;
* organization isolation;
* actor isolation;
* no duplicate Activity;
* deterministic conflict semantics; and
* recovery without guessing records by title or timestamps.

M6.2 must not become a generic idempotency framework for every endpoint.

The frontend may replay a create request only when the authoritative M6.2
contract makes that replay safe. Generic mutation auto-retry remains
forbidden.

### M6.3 — Evidence binary upload and authorized download

M6.3 replaces the current client-declared Evidence metadata boundary with
server-controlled binary storage.

The server owns:

```text
object key generation
binary upload
SHA-256 calculation
size calculation
immutable Evidence metadata
download authorization
```

A storage key is never an authorization credential.

The application must not attempt to create a distributed PostgreSQL/object
transaction. Instead the Gate must define a recoverable consistency protocol.

The preferred failure direction is:

```text
authorize
  ->
server generates opaque storage identity
  ->
stream object upload
  ->
server computes hash and size
  ->
object durability confirmed
  ->
short PostgreSQL transaction
  ->
re-authorize target
  ->
insert immutable Evidence metadata
  ->
insert Activity
  ->
commit
```

If the database transaction fails after a successful object write, the result
is a technical orphan object that must be detected and reconciled after a
defined grace period.

Technical cleanup of an uncommitted orphan is not business deletion of an
accepted immutable Evidence record.

Acceptance must cover at least:

* interrupted upload;
* object write failure;
* object success followed by database failure;
* repeated/replayed upload;
* authorization loss between operations where relevant;
* cross-organization download rejection;
* server-computed hash and size;
* maximum file-size enforcement;
* streaming rather than whole-file memory loading;
* filename normalization;
* content-type handling;
* safe download headers;
* active-content handling such as HTML/SVG;
* immutable committed objects;
* orphan reconciliation; and
* backup/restore hash verification.

Pilot Evidence remains immutable and cannot be deleted by an end user.

Retention expiry, legal hold, business deletion, backup-media erasure and
external sharing remain M7/future governance concerns unless a later Gate
explicitly reopens them.

### M6.4 — Daily scheduled automatic reminder

M6.4 reuses the existing scheduler-neutral reminder sweep rather than moving
cadence into business logic.

The fixed pilot schedule is:

```text
09:00 Asia/Shanghai
daily
```

The scheduler adapter or controlled one-shot runtime owns:

```text
clock
timezone
occurrence/local-date key
invocation
operational status
```

The existing evaluator/sweep remains responsible for target eligibility and
must stay scheduler-neutral.

Recipient selection continues to come from the exact Scenario collaboration
recipient policy.

Required invariants remain:

```text
exact Scenario recipient semantics
closed/inactive/ineligible targets skipped
repeated occurrence creates no duplicate Notification
automatic reminder creates zero Review Activity
Notification delivery rows remain reminder history
no infrastructure-level exactly-once claim
```

Operational evidence must additionally record enough non-business metadata to
detect a missed or unhealthy schedule, including:

```text
last attempted occurrence
last successful occurrence
duration
candidate count
inserted Notification count
dedupe/conflict count
failure class
```

The scheduler must not create a second reminder domain model.

### M6.5 — Authorized snapshot CSV/XLSX export

M6.5 produces a bounded authorization-checked management snapshot for the
requesting organization and user.

CSV and XLSX must consume the same authoritative snapshot rather than running
independent business queries.

Required properties:

* authorization before data disclosure;
* exact organization isolation;
* same logical rows in CSV and XLSX;
* hard maximum of 10,000 authorized rows;
* all-or-nothing failure when the limit is exceeded;
* formula-injection neutralization;
* Chinese text correctness;
* explicit timezone rendering;
* deterministic empty export behavior; and
* no raw unauthorized candidate information.

The export is a snapshot, not a live query stream or a new reporting domain.

The implementation should first construct one immutable in-memory snapshot DTO
and then render CSV/XLSX from that object.

If one export snapshot requires multiple database reads whose consistency
matters, a bounded export-local PostgreSQL `REPEATABLE READ` transaction may be
used. The default isolation level for the rest of EasyAudit-Next must not be
raised merely for export.

### M6-RC — Final Release Candidate joint recovery qualification

M6-RC is a mandatory qualification step after M6.1–M6.5 implementation has
stabilized.

M6.1 proves that the recovery mechanism works. It does not prove that the
final rollout candidate is recoverable after later application, schema and
Evidence changes.

M6-RC therefore freezes one exact final Release Candidate:

```text
API image digest
web/gateway image digest
PostgreSQL/object service identity
configuration revision
secret-reference versions
exact Alembic head
```

The RC recovery set must include real application-level Evidence created
through M6.3, not only the infrastructure fixture used by M6.1.

Against that exact RC, M6-RC must repeat:

```text
joint PostgreSQL/object recovery cut
clean-target PostgreSQL restore
real Evidence object restore
Scenario publication verification
Activity integrity/count verification
Evidence metadata/object hash reconciliation
application/gateway startup
private HTTPS readiness
known-good release rollback
```

The clean restored target must successfully exercise the supported product
boundary sufficiently to prove that database facts, object facts, exact
Scenario versions and release identity are mutually compatible.

M6-RC must again prove:

```text
RPO <= 24 hours
RTO <= 4 hours
```

using the final rollout candidate.

A recovery proof tied only to an earlier M6.1 release cannot satisfy
Pre-rollout readiness after later executable slices have changed the deployed
release.

### Pre-rollout Go/No-Go

Only after M6-RC passes may the project enter the final no-traffic rollout
decision.

Pre-rollout Go/No-Go must verify at minimum:

```text
exact final release identity
private network exposure boundary
trusted HTTPS
green exact-head CI
final-RC recovery evidence
RPO/RTO compliance
rollback target
operational dashboards/metrics/logs
database/resource budgets
scheduler health evidence
Evidence upload/download preflight
authorized export preflight
backup freshness
operator identity
monitoring ownership
rollback trigger
stop conditions
pilot retention decision
```

The pilot retention decision records policy; it does not by itself authorize
automatic deletion.

Go/No-Go does not itself send real user traffic.

A separate explicit user authorization is required before the bounded pilot is
opened.

### Controlled rollout and M6 Program Final Review

After explicit authorization, the controlled pilot remains bounded to the
frozen pilot envelope unless another Gate changes it:

```text
one organization
two departments
10–20 users
10–30 Cases
process_review@1
compliance_review@1
approved private/VPN access only
organization-trusted HTTPS
```

The bounded rollout must include a five-day soak.

The subsequent M6 Program Final Review evaluates runtime evidence rather than
only pre-rollout contracts, including:

```text
real user journeys
both Scenario versions
runtime error/latency evidence
database health
scheduled reminder execution
Evidence storage consistency
backup freshness
operational alerts/stop conditions
absence of cross-organization leakage
absence of unreconciled critical storage anomalies
```

Only this Program Final Review may close M6 as a qualified controlled-pilot
rollout milestone.

## Planned — M7 Data Lifecycle & Governance

M7 owns the long-term lifecycle debt created intentionally by EasyAudit-Next's
strong append-only audit model.

The architecture health review confirms that append-only Activity,
PlatformAuditEvent, immutable Submission/Evidence facts and persistent
Notification delivery history are correct business/audit semantics.

However:

```text
append-only
!=
physical retention forever
```

M7 must define the explicit policy boundary between immutable application
history and privileged lifecycle/archive operations.

### M7.1 — Data lifecycle classification and retention matrix

Define authoritative retention classes for at least:

```text
Activity
PlatformAuditEvent
Submission
Evidence metadata
Evidence binary
Notification
AuthSession
ScenarioVersion
```

The policy must distinguish:

```text
business immutability
operational retention
regulatory retention
archive eligibility
technical cleanup
business deletion
legal hold
backup-media lifecycle
```

No retention policy may silently weaken the normal application prohibition
against mutating historical business facts.

### M7.2 — Notification and session lifecycle

Notification delivery history is operationally useful but may grow materially
after scheduled reminders are enabled.

M7 must define:

* Notification retention/archive policy;
* read/unread history requirements;
* index/table-size monitoring;
* whether old delivery bodies remain online or move to archive; and
* privileged purge/archive boundaries if retention requires them.

AuthSession is not an immutable business fact.

Expired and revoked sessions require bounded cleanup so that routine
authentication does not create an indefinitely growing operational table.

### M7.3 — Activity and Platform Audit archival

Activity and PlatformAuditEvent remain immutable to ordinary application
services.

If long-term volume requires archival or physical retention enforcement, M7
must use an explicitly privileged maintenance path rather than adding DELETE
capability to normal repositories.

Any archival design must preserve:

```text
historical provenance
organization ownership
event identity
timestamp
typed target identity
integrity verification
```

Partitioning must not be introduced merely because the tables are append-only.
It should be justified by measured production size, maintenance or restore
cost.

### M7.4 — Evidence retention, legal hold and erasure

M6.3 intentionally establishes immutable end-user Evidence.

M7 owns the policy questions intentionally deferred from M6:

```text
retention expiry
legal hold
authorized business deletion
technical orphan deletion
object version lifecycle
backup-media erasure
restored-copy retention
external sharing policy
```

Technical cleanup of an uncommitted orphan must remain distinct from deleting
an accepted Evidence fact.

If deletion of committed Evidence becomes legally or operationally required,
the design must preserve auditable tombstone/provenance semantics rather than
silently removing business history.

### M7.5 — Backup and archive lifecycle

Recovery readiness itself creates retained backup copies.

M7 must define:

```text
backup retention generations
backup expiration
recovery-set evidence retention
archive failure domains
object version expiration
secret/key reference rotation effects
backup-media erasure
restore-test frequency
```

Deletion from the primary application database or object store must never be
assumed to imply deletion from historical backup media.

### M7 acceptance principle

M7 succeeds when EasyAudit-Next has an explicit and auditable answer to:

> What data is immutable business truth, how long must it remain available,
> when may it move to archive, who may physically remove it, what must remain
> as provenance, and how are backups/legal holds affected?

M7 must not turn retention into a generic workflow engine or weaken existing
tenant/authorization rules.

## Future — Scale and Enterprise Evolution

Later milestones should be driven by measured pilot evidence rather than
pre-emptive infrastructure expansion.

Potential future work includes:

```text
authorization-safe query scaling
management snapshot scaling
keyset pagination where justified
EXPLAIN/query regression testing
lock-wait and database contention analysis
large-volume soak/load testing
OIDC / enterprise SSO
MFA
directory synchronization
email / enterprise messaging delivery adapters
```

PostgreSQL Row Level Security may be evaluated as an additional defense layer
if EasyAudit-Next later becomes a true multi-organization shared SaaS
deployment. It is not currently a replacement for application authorization
or strong organization-scoped foreign keys.

## Deferred / non-goals

The following remain deferred unless separately justified by a future Gate:

```text
microservice decomposition
distributed transactions
Kafka / event-bus architecture
Redis as business truth
generic distributed locks
BPMN / workflow designer
universal form builder
runtime entity designer
custom dashboard builder
anonymous responsibility tokens
SupervisionRecord / ManagementTask domain
native mobile app / offline PWA
AI-generated business truth
```

EasyAudit-Next remains a Modular Monolith. Review Core, exact immutable
Scenario policy, resource-scoped authorization, strong organization-aware
foreign keys and PostgreSQL transaction boundaries remain the architectural
center of gravity.

Future operational hardening must improve recoverability, observability,
security and scale around that core rather than replacing it without evidence.
