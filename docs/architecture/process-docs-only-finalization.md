# Process Hardening Gate Draft: Docs-only Gate Finalization

## Purpose and current boundary

This is an independent process-hardening Gate Draft. It defines how a
documentation-only milestone can be reviewed and finalized without weakening
the executable `fixed_head` protocol. The current diff is a
documentation-only Gate Draft, while this process slice's state correctly
keeps `candidate_kind: executable`; it changes state and process documents,
but does not yet change the validator or its tests.

The candidate is based exactly on:

~~~text
main@b4b74f4b4dd0ca46ee19d187c49d3f95de3eae42
~~~

The current Gate Draft may change only the files declared by
`.easyaudit/development-state.json`. It must not implement M6.0, M6.1, a new
API, persistence behavior, deployment behavior or the proposed validator
changes. The validator and focused tests become eligible only after this
Gate Draft passes Architecture / Acceptance Review and the outer state moves
to `IMPLEMENTATION`.

## Problem to close

The existing Gate assumes that `fixed_head` identifies an executable candidate
that completed Implementation Review. A docs-only candidate has no executable
candidate and must therefore not fabricate a `fixed_head` or silently skip
the repository's merge controls. The process change must make this distinction
machine-checkable and independent of a milestone's self-declared scope.

## Proposed candidate kinds

The state may explicitly set `candidate_kind` to `executable` or `docs-only`.
Omitting the field preserves the current executable behavior.

### Executable candidate

`fixed_head` retains its existing meaning: the last executable candidate that
completed Implementation Review. `FINAL_REVIEW` and `MERGE_AUTHORIZED` require
a resolvable `fixed_head` that is an ancestor of the control head. Only paths
in `finalization_allowed_paths` may change after that head.

### Docs-only candidate

The implementation that follows this Gate Draft must enforce all of these
invariants in the validator, regardless of the milestone's `allowed_paths`:

- `fixed_head` is null or empty; it is never used as the docs-only review head;
- `GATE_DRAFT` has no `docs_review_head`;
- `GATE_REVIEW` and `MERGE_AUTHORIZED` require a non-empty, resolvable
  `docs_review_head` that is an ancestor of the current control head;
- changes after `docs_review_head` are limited to
  `finalization_allowed_paths`;
- `IMPLEMENTATION` and `FINAL_REVIEW` reject `docs-only`; and
- an active docs-only state at `MERGED` is invalid. A merged docs-only
  candidate is represented by `active=false` after the merge, so it cannot
  bypass the reviewed-head check.

The validator must apply a process-owned positive allowlist to the complete
`BASE...control_head` change set. For a docs-only candidate, every changed
path must be either `.easyaudit/development-state.json` or under `docs/**`.
The milestone's `scope.allowed_paths` must be a subset of that allowlist and
must not expand it. `finalization_allowed_paths` must be a subset of the
single state path. Any source, script, test, CI, OpenAPI, migration, frontend,
container, deployment or other non-document path therefore fails even when a
milestone explicitly lists it as allowed. The process-owned allowlist may only
be expanded by a separately reviewed executable process Gate.

For a GitHub pull request, the control head is the actual PR head from the
event payload. A synthetic merge commit must not replace the candidate or
control identity when checking ancestry or the finalization-only delta.

## Proposed docs-only lifecycle

Once the validator implementation is reviewed and merged, a docs-only
candidate follows:

~~~text
GATE_DRAFT
  -> GATE_REVIEW
  -> MERGE_AUTHORIZED
  -> MERGED (then active=false)
~~~

There is no `IMPLEMENTATION` or `FINAL_REVIEW` for a docs-only product
candidate because it has no executable candidate. The transition to
`MERGE_AUTHORIZED` still requires independent Architecture / Acceptance Review,
exact-head GitHub Actions and explicit user merge authorization. C2C `DONE`, a
local check or a state field never authorizes a merge.

The process-hardening slice itself remains an executable tooling change and
must follow the ordinary lifecycle after this Gate Draft passes:

~~~text
GATE_DRAFT -> GATE_REVIEW -> IMPLEMENTATION -> FINAL_REVIEW
-> MERGE_AUTHORIZED -> MERGED
~~~

The scope must be widened only by a reviewed state transition into
`IMPLEMENTATION`. The validator/tests implementation must then receive its
own Implementation Review and an executable `fixed_head` before Final Review.

## Review Bundle contract

For a docs-only candidate, `gate-proof.json` must record both the explicit
`candidate_kind` and `docs_review_head`. The candidate diff is
`BASE...docs_review_head`; the control diff is `docs_review_head..control_head`
and may contain only finalization metadata. The working-tree diff is always
independent evidence.

Bundle generation and validation must rebuild those refs and reject stale,
mixed-generation or non-ancestor heads. The process-hardening implementation
itself requires its own exact-head GitHub Actions run; local tests and C2C
execution records are supporting evidence only.

## Required implementation evidence after this Draft

The next phase must add focused tests for:

- a real docs-only `GATE_REVIEW` topology with a document candidate followed
  by a state-only control commit;
- missing, malformed and non-ancestor `docs_review_head` rejection;
- executable changes after `docs_review_head` rejection;
- rejection when `allowed_paths` tries to include any path outside the
  process-owned `.easyaudit/development-state.json` / `docs/**` allowlist,
  including source, scripts, tests, CI, migrations, frontend, container or
  deployment paths;
- docs-only rejection of `fixed_head`, `IMPLEMENTATION`, `FINAL_REVIEW` and an
  active `MERGED` state;
- docs-only `MERGE_AUTHORIZED` acceptance using the reviewed document head; and
- actual PR-head control behavior under a synthetic merge checkout.

## Non-goals

This Gate Draft does not change product behavior, account or Evidence
lifecycle, authorization semantics, deployment, CI configuration, API or
persistence. It does not authorize M6.0 review, M6.1 implementation, external
deployment, real traffic or any merge.
