# M6.0 Controlled Pilot Rollout Readiness v2

## Gate status and boundary

This document is the M6.0 Architecture / Acceptance Gate Draft. It is a
documentation-only slice that freezes the controlled-pilot rollout plan,
dependencies, evidence contract and non-goals for the M6 work. It does not
authorize application implementation, infrastructure deployment, production
traffic, a data migration or a merge.

The candidate is based exactly on:

```text
main@e643a3f43032908d8a0c59d2f6819ae42d38504a
```

The outer lifecycle for this candidate is the docs-only lifecycle:

```text
GATE_DRAFT -> GATE_REVIEW -> MERGE_AUTHORIZED -> MERGED (then active=false)
```

M6.0 must not enter `IMPLEMENTATION` or `FINAL_REVIEW`. Each later M6
executable slice requires its own Gate, independent scope review, exact-head
evidence and final review. This roadmap is not implementation authorization.

## Baseline and objective

M5.1–M5.5 established the reusable review platform, the integrated React
surface and a controlled-pilot proof for the two supported exact Scenario
versions. The current product has client-registered Evidence metadata, but it
does not yet provide production rollout infrastructure, strong create
idempotency, binary Evidence storage, recurring reminders or authorized
spreadsheet export.

M6.0 freezes the smallest ordered plan to close those rollout-readiness gaps
without moving business truth out of the existing Review Core and exact
Scenario policy seams. The objective is a bounded, recoverable pilot rather
than a general-purpose workflow or storage platform.

## Controlled-pilot envelope

The pilot envelope is fixed for all M6 slices unless a later Gate explicitly
reopens it:

- one organization, two departments, 10–20 users and 10–30 Cases;
- both `process_review@1` and `compliance_review@1` must be exercised in real
  journeys;
- access is limited to approved VPN or another approved private network;
- HTTPS uses a certificate chain trusted by the organization; and
- the service is not opened to the public Internet.

The pilot is not a production launch. The Pre-rollout Readiness review must
record an explicit operator, rollback boundary, monitoring plan, stop
conditions and a retention decision before any rollout authorization. That
retention decision is a pilot policy record; it does not authorize automatic
retention deletion. No M6 slice may infer public access, unrestricted
tenancy, automatic retention deletion or an external sharing capability.

## Ordered M6 v2 slices

The following order is fixed. A later item cannot be implemented merely
because it appears here; its own Gate must be reviewed first.

### M6.1 — No-traffic infrastructure deployment

Deploy only the minimum private pilot substrate: PostgreSQL, private
S3-compatible object storage, a fixed application image digest, configuration
references and secret references. Prove a fresh deployment, backup/restore,
rollback and the following recovery objectives:

```text
RPO <= 24 hours
RTO <= 4 hours
```

M6.1 does not add Evidence upload/download APIs, change authorization or
expose the service to real pilot traffic. Secrets must remain outside Git and
outside Review Bundle contents. Its recovery evidence must use one jointly
verifiable recovery set, not unrelated database and object-store restores.
The set must have a manifest linking the PostgreSQL backup identity and point
in time, object-store snapshot/version or object manifest, application image
digest, configuration revision, secret-reference identifiers (never secret
values), restore order and compatibility checks. M6.1 may use a controlled
infrastructure fixture to validate object recovery; M6.3 must separately
prove application-level database/object compensation with real Evidence.

### M6.2 — Plan/Case creation idempotency and unknown-result recovery

Define and implement only the create operations needed by the plan-first
flow. A stable idempotency key and an identical request must converge to one
result; reusing the key with a different payload must fail safely. The design
must cover PostgreSQL/API concurrency, replay, organization and user
isolation, Activity non-duplication and browser response ambiguity.

M6.2 must not become a generic idempotency framework, change the existing
plan-first checkpoint, or guess an object by title after an unknown response.

### M6.3 — Evidence binary upload and authorized download

Replace the current client self-reported `storage_key`, `sha256` and `size`
metadata boundary with server-controlled binary storage, server-computed
hash/size and an authorization-checked download path. The database record and
object must have a recoverable consistency strategy for failures on either
side. Storage keys must never be exposed as an authorization substitute.

Pilot Evidence is immutable and non-overwritable; an end user cannot delete
it. Retention expiry, business deletion, backup-media erasure, legal hold and
external sharing are separate future decisions and are not included in M6.3.

### M6.4 — Daily 09:00 Asia/Shanghai in-app reminder

Reuse the existing scheduler-neutral one-shot sweep. The scheduler adapter or
one-shot entrypoint owns the `09:00 Asia/Shanghai` cadence, an explicit clock
input and the local-date occurrence key; the existing sweep/evaluator remains
scheduler-neutral. The recipient is selected by the exact-version Scenario's
collaboration-recipient resolver, not inferred from a permission set. A
repeated occurrence creates no duplicate Notification and automatic reminders
always create zero Review Activity; Notification delivery rows are the
reminder history. The design must not claim infrastructure-level “exactly
once” delivery. Closed, inactive or otherwise ineligible targets must not
receive a reminder.

### M6.5 — Authorized snapshot CSV/XLSX export

Generate a bounded, authorization-checked snapshot for the requesting
organization and user. CSV and XLSX must represent the same snapshot, enforce
a hard 10,000-row limit and neutralize formula injection. Chinese text,
timezone rendering and empty results are first-class acceptance cases.

The export is a snapshot, not a live query stream, and does not authorize
cross-organization export, arbitrary background jobs or a new reporting
model.

### M6 Pre-rollout Readiness, rollout and Program Final Review

After M6.1–M6.5 have independently passed their Gates, a Pre-rollout
Readiness review must verify the fixed image digest, private access/TLS,
joint recovery evidence, Evidence preflight, authorized export, operator,
monitoring, rollback trigger, stop conditions and the pilot retention
decision. It must not include or imply real pilot traffic. A user must then
explicitly authorize the bounded controlled rollout. Only after that
authorization may the five-day soak run; the soak, five actual reminder
schedule points and runtime events belong to the subsequent M6 Program Final
Review. This ordering prevents a readiness Gate from depending on traffic it
is supposed to authorize.

## Cross-slice invariants

All M6 slices preserve these repository and product invariants:

- the backend remains authoritative for authorization, lifecycle, tenancy,
  scenario policy and provenance;
- exact `(scenario_key, scenario_version)` resolution remains fail-closed;
- organization isolation applies to every API, object, export and reminder;
- Review Core and Scenario-specific business truth are not duplicated;
- append-only Activity records are not duplicated by retries or sweeps;
- credentials, secret references, raw storage keys and private deployment
  material do not enter Git or C2C evidence; and
- any missing schema capability, new authorization semantic, lifecycle rule,
  concurrency model or deployment assumption stops the current slice and
  requires a revised Gate.

## Evidence and governance

Every executable slice must define its own focused tests and real PostgreSQL,
API and browser evidence before Implementation Review. Before Final Review,
Codex must produce a current Review Bundle and `check --require-clean
--require-bundle`; GitHub Actions must be green on the exact reviewed head.
Local tests and C2C execution summaries are supporting evidence, not a
substitute for GitHub evidence.

M6.0 itself requires only document validation, scope validation, a clean
working tree and an independent Architecture / Acceptance Review. The M6.0
candidate must contain only the state file, this charter, its acceptance
document and the roadmap. It must not modify source, tests, migrations,
OpenAPI, CI, containers or deployment files.

## Success criteria and next action

M6.0 succeeds when the pilot envelope, ordered dependencies, acceptance
evidence, recovery boundaries, security limits and deferred decisions are
unambiguous; the roadmap records M5 completion and the M6 v2 sequence; the
docs-only Gate check and Review Bundle are clean; and no executable work is
hidden in the candidate.

The next allowed action after this Draft is independent Architecture /
Acceptance Review. Until that review passes, no M6.1 implementation,
deployment, real traffic or later-slice code is authorized.
