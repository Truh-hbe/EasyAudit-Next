# M2.5 — Verification / Closure

M2.5 completes the first authenticated Process Review business loop by adding formal verification,
Finding reopen, and ReviewCase closure on top of the M2.4 rectification aggregate.

## Scope

M2.5 owns only these capabilities:

- reviewer approval and rejection of a `verifying` Finding;
- immutable verification Submission history;
- explicit Finding reopen from `closed` back to `rectifying` with a required reason;
- ReviewCase closure from `awaiting_closure` only when every Finding is terminal;
- PostgreSQL concurrency coordination between Case closure and Finding transitions that can change
  the Case-level terminality predicate; and
- the end-to-end Process Review closure path.

Notification, Workbench, Dashboard, reminder scheduling, a second Scenario, and legacy migration remain
outside M2.5.

## Domain semantics

Process Review v1 already owns the workflow meanings:

```text
Finding

VERIFYING --approve--> CLOSED
VERIFYING --reject(reason)--> RECTIFYING
CLOSED    --reopen(reason)--> RECTIFYING

ReviewCase

AWAITING_CLOSURE --close--> CLOSED
```

`approve` and `reject` are formal verification Submissions. `reopen` is a Finding lifecycle transition
with an append-only Activity; it is not itself a verification Submission.

A ReviewCase may close only when all of its Findings are terminal:

```text
terminal Finding := lifecycle in {closed, voided}
```

An empty Finding set therefore satisfies the terminality predicate.

## Cross-aggregate concurrency invariant

The M2.5 hard invariant is:

> A committed `closed` ReviewCase must never contain a non-terminal Finding.

The dangerous race is not a single-row Case CAS or Finding CAS. It is the Case-level predicate
computed over a set of child Findings while another transaction can change one Finding's terminality.

M2.5 therefore introduces a dedicated repository extension for Case/Finding closure coordination.
The base `ReviewCoreRepository` remains unchanged.

```text
VerificationClosureRepository
    extends RectificationRepository

    lock_case_for_closure(...)
    list_findings_for_closure(...)
```

`lock_case_for_closure()` uses an organization-scoped PostgreSQL `SELECT ... FOR UPDATE` on the
parent ReviewCase row. The returned ORM state must be refreshed after lock wait.

`list_findings_for_closure()` must refresh the decisive Finding rows from PostgreSQL rather than
reusing a pre-lock SQLAlchemy identity-map snapshot.

## Shared Case guard

The parent ReviewCase row is the serialization point for every M2.5 operation that can change the
Case-level all-Findings-terminal predicate.

At minimum the shared Case guard is acquired by:

- verification approve;
- verification reject;
- Finding reopen; and
- ReviewCase close.

This is intentionally coarser than a per-Finding-only protocol. M2.5 prefers a simple aggregate
consistency boundary over higher write concurrency. Existing M2.4 rectification writes keep their
Finding-level guard because they cannot make a terminal Finding non-terminal and Case closure cannot
succeed while a Finding is `rectifying` or `verifying`.

## Lock order

M2.5 fixes one lock order:

```text
ReviewCase -> Finding -> Submission / Activity
```

Verification/reopen first acquires the parent Case guard, then refreshes/locks the target Finding.
Case closure acquires the Case guard and then refreshes the complete Finding set.

No M2.5 path may acquire a Finding lock and then attempt to acquire the Case guard.

This lock order is separate from M2.4's rectification-only order:

```text
Finding -> Action / Assignee / Evidence / Submission
```

The two protocols do not form a cycle because M2.4 does not subsequently request the Case guard.

## Verification cutover

A verification request follows this order:

```text
initial object lookup / authorization facts
        ↓
lock parent ReviewCase
        ↓
confirm Case still permits verification
        ↓
refresh target Finding after lock wait
        ↓
confirm expected Finding lifecycle
        ↓
Scenario SubmissionDecision
        ↓
Finding CAS
        ↓
immutable verification Submission
        ↓
Activity
        ↓
request transaction commit
```

If the caller observed `verifying` before waiting but the refreshed Finding has changed lifecycle,
the request fails with the existing `409 Concurrent Finding transition` semantics rather than being
reclassified as ordinary Scenario validation.

Approve produces:

```text
Submission purpose = verification
payload.result = approved
Finding VERIFYING -> CLOSED
Activity finding.approved
```

Reject requires a non-blank comment/reason and produces:

```text
Submission purpose = verification
payload.result = rejected
Finding VERIFYING -> RECTIFYING
Activity finding.rejected
```

Submission, Finding CAS, and Activity remain one request transaction.

## Reopen cutover

Reopen is authorized by the Scenario-owned `reopen_finding` permission and requires a reason.

The operation acquires the parent Case guard before refreshing the Finding. It must reject reopen if
that Case has already become `closed` or otherwise no longer permits the operation.

This prevents the sequence:

```text
Case close reads all Findings terminal
        ↓
Case commits CLOSED
        ↓
stale reopen commits Finding RECTIFYING
```

The legal serialized outcomes are:

```text
reopen wins
→ Finding RECTIFYING
→ Case close rereads non-terminal Finding and fails business validation
```

or:

```text
Case close wins
→ Case CLOSED
→ reopen obtains the Case guard afterward and is rejected
```

## Case closure cutover

A close request follows this order:

```text
initial Case lookup / authorization
        ↓
lock parent ReviewCase
        ↓
confirm expected lifecycle is still AWAITING_CLOSURE
        ↓
refresh complete Finding set after lock wait
        ↓
compute all_findings_terminal
        ↓
Scenario ReviewCase workflow
        ↓
Case CAS
        ↓
Activity
        ↓
request transaction commit
```

The Case workflow receives the real aggregate predicate. M2.2's placeholder
`all_findings_terminal=False` must not remain on the close path.

If another caller already changed the Case lifecycle while this request waited on the guard, the
loser retains `409 Concurrent ReviewCase transition` semantics.

## Authorization precedence

Verification and reopen first require visibility to the Finding/Case before reading decisive
aggregate facts. Scenario-specific action permissions are checked before mutation.

The intended API error contract remains:

- `403` — authenticated user lacks the required business relationship;
- `404` — organization-scoped object lookup fails;
- `422` — Scenario/business validation fails;
- `409` — stale lifecycle / concurrent transition / persistence conflict.

Authorization failures must not disclose whether sibling Findings are terminal or whether the Case is
currently closable.

## SQLAlchemy refresh requirement

PostgreSQL row locks serialize transactions but do not invalidate an already-populated ORM identity
map. Any decisive object or aggregate read performed after waiting on the Case guard must explicitly
refresh persisted state, using `populate_existing=True` or an equivalent mechanism.

This requirement applies to:

- the locked ReviewCase;
- the target Finding for verification/reopen; and
- the Finding set used by closure.

## Scenario boundary

Review Core supplies only Scenario-neutral facts:

```text
current Case lifecycle
current Finding lifecycle
all_findings_terminal
reason
relationship-derived AuthorizationContext
Submission payload / purpose
```

Process Review v1 continues to own:

- who may verify/reopen/close;
- which lifecycle transitions are legal;
- rejection/reopen reason requirements; and
- verification Submission validation.

Review Core must not import `process_review` or branch on a concrete Scenario key/version.

## End state

M2.5 is complete only when the authenticated end-to-end chain is proven through PostgreSQL:

```text
create/schedule/start Case
→ create + issue Finding
→ rectification plan
→ Actions + Evidence
→ completion Submission
→ Finding VERIFYING
→ reject
→ re-rectify + submit
→ approve
→ Finding CLOSED
→ finish fieldwork
→ all Findings CLOSED/VOIDED
→ ReviewCase CLOSED
```

Every lifecycle mutation must leave append-only Activity history and every formal verification must
leave an immutable Submission.