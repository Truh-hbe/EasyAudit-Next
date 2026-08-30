# M6.0 Controlled Pilot Rollout Readiness Acceptance

## 1. M6.0 documentation Gate

The M6.0 candidate is acceptable only when all of the following are true:

1. the candidate base is exactly the post-rebaseline `main` commit recorded
   in `.easyaudit/development-state.json`;
2. the changed paths are exactly the state file, `roadmap.md`, this document
   and the M6.0 charter;
3. the state is `active=true`, `milestone=M6`,
   `slice=M6.0-controlled-pilot-rollout-readiness-v2`,
   `phase=GATE_DRAFT`, `candidate_kind=docs-only`, with no fixed or reviewed
   executable head;
4. the charter freezes the one-organization pilot envelope, private access,
   exact Scenario versions, ordered M6.1–M6.5 slices and Final Readiness
   boundary;
5. the roadmap records the completed M5.1–M5.5 baseline and explicitly says
   that a roadmap entry does not authorize executable work; and
6. no source, test, migration, OpenAPI, CI, container, deployment or runtime
   behavior is changed.

M6.0 is a docs-only lifecycle. It must not enter `IMPLEMENTATION` or
`FINAL_REVIEW`. After independent review, the only permitted outer transition
is `GATE_REVIEW -> MERGE_AUTHORIZED -> MERGED`, followed by `active=false`.

## 2. Pilot envelope acceptance

The later Final Readiness evidence must prove a bounded pilot with:

- one organization;
- two departments;
- 10–20 users;
- 10–30 Cases;
- real completion of both `process_review@1` and `compliance_review@1`;
- approved VPN/private-network access only; and
- HTTPS trusted by the organization, with no public Internet exposure.

The evidence must identify the tested organization and users without exposing
credentials, private keys, raw storage keys or customer exports.

## 3. Minimum evidence for later executable slices

The following is the minimum evidence contract that each later Gate must
adopt and refine. Listing an item here does not authorize its implementation.

### M6.1 — Infrastructure and recovery

The M6.1 Gate must require real evidence of:

- a no-traffic fresh deployment using a fixed image digest;
- PostgreSQL and private S3-compatible storage on the approved private
  network;
- organization-trusted TLS and no public exposure;
- configuration and secret references with no secret material in Git or
  bundles;
- a backup and restore rehearsal with measured `RPO <= 24h` and
  `RTO <= 4h`;
- a rollback rehearsal and explicit stop condition; and
- absence of Evidence upload/download API changes in this slice.

The evidence must distinguish infrastructure readiness from application
readiness and must not claim that an unused storage service provides an
Evidence lifecycle.

### M6.2 — Create convergence and unknown results

The M6.2 Gate must require real PostgreSQL/API concurrency and replay tests
showing:

- the same idempotency key and identical request converge to one Plan or Case
  result;
- the same key with a different payload returns a safe conflict;
- retries do not duplicate Activity or create a second Plan/Case;
- organization and user authorization remain isolated under replay;
- a definitive validation rejection preserves the plan-first checkpoint and
  permits only the intended Case retry; and
- a browser transport/response ambiguity does not blindly repost or guess by
  title, and has a deterministic reconciliation or navigation path.

The Gate must state the bounded key scope, retention and conflict semantics;
it may not silently introduce a universal idempotency layer.

### M6.3 — Binary Evidence lifecycle

The M6.3 Gate must require real object-storage and API evidence showing:

- the server receives or controls the binary and computes hash and size;
- an authorized user can upload and download the intended Evidence;
- a foreign organization is denied without existence or name leakage;
- raw storage keys are not exposed or accepted as authorization;
- database/object partial failures have a defined compensation or recovery
  path; and
- after recovery, the immutable Evidence remains downloadable to an
  authorized user.

The test must prove no overwrite and no end-user delete. Retention, deletion,
backup erasure, legal hold and external sharing require separate Gates.

### M6.4 — Daily reminder

The M6.4 Gate must require evidence that:

- the daily boundary is evaluated in `Asia/Shanghai`, including a date-boundary
  case;
- repeated calls with the same occurrence key do not duplicate delivery or
  Activity;
- closed, inactive and otherwise ineligible targets receive no reminder;
- the scheduler invokes a one-shot sweep and does not claim exactly-once
  infrastructure delivery; and
- the final controlled-pilot soak records five actual schedule points.

The evidence must identify the recipient using Scenario-owned authorization
and must not invent a second notification truth model.

### M6.5 — Authorized export

The M6.5 Gate must require evidence that:

- an authorized request creates a snapshot with a stable provenance/timezone
  marker;
- CSV and XLSX contain equivalent rows and columns from the same snapshot;
- more than 10,000 rows is rejected or bounded without partial export;
- spreadsheet formula injection is neutralized;
- Chinese text, timezone rendering and an empty result are correct; and
- cross-organization and unauthorized export requests are denied without
  leaking data.

The evidence must not establish a live export stream or a new reporting
aggregate.

## 4. Final Readiness acceptance

The Final Readiness Gate may proceed only after the five executable slices
have independently passed their reviews. Its minimum evidence package is:

1. the fixed image digest and private access/TLS record;
2. two real Evidence-capable journeys, one for each exact Scenario version;
3. a PostgreSQL/object recovery rehearsal and measured RPO/RTO;
4. an authorized CSV/XLSX export with the 10,000-row and injection controls;
5. five-day controlled-pilot soak evidence including five actual reminder
   schedule points;
6. rollback evidence, operator ownership, monitoring and stop conditions; and
7. a current Review Bundle plus exact-head GitHub Actions evidence for all
   required backend, frontend, PostgreSQL, API and browser acceptance jobs.

Only a subsequent reviewed Final Readiness Gate can authorize controlled pilot
traffic. M6.0, its roadmap entry and any local pass cannot do so.

## 5. Review, evidence and no-go rules

For every executable M6 slice, Go requires:

- no unresolved P1 or P2 findings;
- focused tests plus real PostgreSQL/API/browser evidence where applicable;
- a clean current Review Bundle;
- GitHub Actions green on the exact reviewed candidate head;
- explicit scope compliance and no hidden deployment or traffic change; and
- documented rollback and known limitations.

No-Go applies when any evidence depends on a hidden fixture shortcut, stale
state or bundle, synthetic rather than actual PR head, skipped PostgreSQL or
browser acceptance, leaked secret/storage identity, unresolved authorization
boundary, or an unreviewed architecture expansion.

## 6. M6.0 exit criteria

M6.0 exits only when the four-file docs-only candidate passes JSON validation,
`git diff --check`, the active Gate check, Review Bundle generation and
`check --require-clean --require-bundle`, followed by independent
Architecture / Acceptance Review. The next state may be `GATE_REVIEW`; it
must not be `IMPLEMENTATION` or `FINAL_REVIEW`.
