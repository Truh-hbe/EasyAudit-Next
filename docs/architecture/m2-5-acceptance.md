# M2.5 Acceptance Gate

M2.5 is ready for Final Architecture Review only when CI proves all of the following.

## Architecture boundary

- Review Core remains free of concrete Scenario imports and `process_review` branching.
- Process Review v1 continues to own verification/reopen/closure workflow and authorization rules.
- The base `ReviewCoreRepository` is not expanded with M2.5-only aggregate locking concerns.
- A dedicated verification/closure repository extension owns Case-level concurrency coordination.
- Existing M2.4 rectification repository boundaries and Finding-level guard semantics remain intact.

## Verification

- Verification approve is accepted only from `Finding=verifying`.
- Verification reject is accepted only from `Finding=verifying` and requires a non-blank reason/comment.
- Approve creates one immutable verification Submission, advances the Finding to `closed`, and appends one `finding.approved` Activity in the same request transaction.
- Reject creates one immutable verification Submission, returns the Finding to `rectifying`, and appends one `finding.rejected` Activity in the same request transaction.
- Verification authorization comes from the exact ScenarioVersion policy and does not grant platform administrators implicit reviewer authority.
- An unrelated same-organization user is denied visibility/authorization before verification lifecycle or aggregate facts can be disclosed.
- Verification Submission UPDATE and DELETE remain rejected by PostgreSQL append-only protection.
- A persistence failure after Finding CAS rolls back the Finding transition, Submission, and Activity together.

## Reopen

- Finding reopen is accepted only from `closed` and requires a non-blank reason.
- Reopen authorization comes from the exact ScenarioVersion policy.
- Reopen appends one lifecycle Activity and does not create a verification Submission.
- Reopen cannot succeed after its parent ReviewCase has committed `closed`.
- A caller that observed `closed` Finding state before waiting on the Case guard but sees a changed lifecycle after the wait receives `409 Concurrent Finding transition`.

## Case closure

- ReviewCase close is accepted only from `awaiting_closure`.
- The closure workflow receives the real persisted aggregate predicate, not the old placeholder `all_findings_terminal=False`.
- A Case closes when and only when every persisted Finding is terminal (`closed` or `voided`).
- A Case with any `open`, `rectifying`, or `verifying` Finding cannot close.
- Case closure appends one transition Activity atomically with the Case lifecycle CAS.
- Two concurrent Case close callers from the same old lifecycle yield one success, one `409 Concurrent ReviewCase transition`, and one closure Activity.

## Cross-aggregate PostgreSQL concurrency gate

The following is a hard release gate:

> Case closure racing with a Finding transition must never persist a `closed` ReviewCase containing a non-terminal Finding.

CI must include real PostgreSQL double-Session tests proving at least these races.

### Close vs final verification approve

Both legal serializations are accepted:

```text
approve wins
→ Finding CLOSED
→ close obtains Case guard, rereads all Findings terminal
→ Case CLOSED
```

or:

```text
close wins Case guard while final Finding is still VERIFYING
→ close rereads non-terminal Finding and fails business validation
→ approve later succeeds
→ Case remains AWAITING_CLOSURE
```

It is never legal to persist `Case=CLOSED + Finding=VERIFYING`.

### Close vs Finding reopen

Both legal serializations are accepted:

```text
reopen wins
→ Finding RECTIFYING
→ close rereads non-terminal Finding and fails business validation
```

or:

```text
close wins
→ Case CLOSED
→ reopen obtains Case guard afterward and is rejected
```

It is never legal to persist `Case=CLOSED + Finding=RECTIFYING`.

### Finding create vs fieldwork cutover

Finding creation also changes the Case-level all-Findings-terminal set. A caller that observed
`Case=IN_PROGRESS` must not be able to insert a new `OPEN` Finding after fieldwork has already crossed
to `AWAITING_CLOSURE` (and potentially onward to `CLOSED`).

Both legal serializations are accepted:

```text
create wins Case guard
→ OPEN Finding is persisted
→ finish_fieldwork obtains Case guard afterward
→ Case AWAITING_CLOSURE with the non-terminal Finding visible to future close
```

or:

```text
finish_fieldwork wins Case guard
→ Case AWAITING_CLOSURE
→ stale create obtains Case guard afterward
→ create receives ReviewCase concurrency conflict and persists no Finding
```

A late Finding insert after the Case cutover is never legal.

## Shared Case guard and stale snapshots

- M2.5 operations that can affect the all-Findings-terminal predicate use the same organization-scoped parent ReviewCase `FOR UPDATE` guard.
- Finding creation uses that same Case guard before its decisive Case-lifecycle validation and insert.
- M2.5 lock order is consistently `ReviewCase -> Finding -> Submission/Activity`.
- No M2.5 path acquires a Finding lock and then requests the parent Case guard.
- The locked Case is refreshed after lock wait.
- The target Finding used by verification/reopen is refreshed after lock wait.
- The complete Finding set used for closure is refreshed after lock wait.
- SQLAlchemy identity-map state observed before waiting cannot determine post-lock creation, verification, or closure decisions.

## Error contract

- `403` remains authorization failure.
- `404` remains organization-scoped lookup failure.
- `422` remains Scenario/business validation failure, including closure with non-terminal Findings.
- `409` remains stale lifecycle / concurrent transition / persistence conflict.
- Waiting on a guard and discovering that the caller's expected lifecycle changed is reported as concurrency, not ordinary business validation.

## Full Process Review E2E

PostgreSQL integration coverage must prove the complete authenticated chain:

```text
ReviewPlan
→ ReviewCase create / schedule / start
→ Finding create / participants / issue
→ rectification plan Submission
→ multiple ActionItems / assignees / Evidence
→ Action completion
→ completion Submission
→ Finding VERIFYING
→ reviewer reject
→ re-rectification
→ completion Submission
→ reviewer approve
→ Finding CLOSED
→ finish fieldwork
→ ReviewCase AWAITING_CLOSURE
→ every Finding CLOSED/VOIDED
→ ReviewCase CLOSED
```

The E2E must additionally prove:

- every lifecycle transition has one append-only Activity;
- every formal rectification/verification submission is immutable and traceable;
- cross-organization reads/writes are rejected;
- unrelated users cannot use object IDs as an authorization boundary bypass;
- state cannot be changed through ordinary PATCH/update APIs;
- the Case resolves the exact historical `(scenario_key, scenario_version)` policy throughout; and
- all previous M1, M2.2, M2.3, and M2.4 regression, atomicity, CAS, and PostgreSQL race tests remain green.

The PR remains Draft and unmerged after this gate. M2 Final Review does not begin until M2.5 Final
Architecture Review explicitly releases this slice.