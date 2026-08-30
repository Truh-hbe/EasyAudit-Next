# Docs-only Gate Finalization Acceptance — Gate Draft

## Gate identity and current scope

This Gate Draft is based on:

~~~text
main@b4b74f4b4dd0ca46ee19d187c49d3f95de3eae42
~~~

The current candidate is a docs-only Gate Draft. Its changed files must be
limited to the active state, the two process documents named by the state and
the necessary workflow documentation. It must not include validator code,
tooling tests, product source, migrations, OpenAPI, frontend, CI, container or
deployment files. Those changes require a later `IMPLEMENTATION` phase after
this Draft is independently reviewed.

## Architecture / Acceptance Review criteria

Review must confirm that the proposed process change:

- distinguishes executable `fixed_head` from docs-only `docs_review_head`;
- preserves the existing executable lifecycle and finalization-only rule;
- makes docs-only path restrictions process-owned rather than dependent on a
  milestone's self-declared scope;
- rejects active docs-only `MERGED` and requires `active=false` after merge;
- uses the actual PR head as control identity, not a synthetic merge commit;
- separates candidate, control and working-tree evidence in the Bundle; and
- explicitly does not authorize M6.0, M6.1, external deployment, real traffic
  or a merge.

## Required implementation contract after Draft approval

Only after this Draft reaches `GATE_REVIEW` and the process state moves to
`IMPLEMENTATION` may the candidate add validator and focused-test changes. The
implementation must then preserve executable behavior:

- an omitted `candidate_kind` means `executable`;
- executable `FINAL_REVIEW` and `MERGE_AUTHORIZED` require a resolvable,
  ancestor `fixed_head`; and
- post-fixed-head changes remain limited to `finalization_allowed_paths`.

For `candidate_kind: docs-only`, the validator must require:

- null/empty `fixed_head`;
- no `docs_review_head` in `GATE_DRAFT`;
- a non-empty, resolvable ancestor `docs_review_head` in `GATE_REVIEW` and
  `MERGE_AUTHORIZED`;
- finalization-only changes after the reviewed head;
- rejection of `IMPLEMENTATION`, `FINAL_REVIEW` and active `MERGED`;
- rejection of executable paths even when a state lists them as allowed; and
- candidate/control Bundle refs based on the reviewed document head and the
  actual PR head respectively.

## Required implementation tests

The focused matrix must include existing executable acceptance/rejection plus
real Git-topology tests for:

- document candidate plus state-only control commit;
- missing, malformed and non-ancestor `docs_review_head`;
- executable changes after the reviewed head;
- executable paths smuggled into docs-only `allowed_paths`;
- docs-only `fixed_head`, `IMPLEMENTATION`, `FINAL_REVIEW` and active `MERGED`
  rejection;
- docs-only `MERGE_AUTHORIZED` acceptance; and
- actual PR-head control under a synthetic merge checkout.

The executable-path test must use a real temporary Git topology, not only a
mocked state, so the process rule cannot be satisfied by a test that assumes
its own answer.

## Outer lifecycle and evidence

The current Draft remains in `GATE_DRAFT` until independent Review. After it
passes, the process-hardening implementation follows:

~~~text
GATE_DRAFT -> GATE_REVIEW -> IMPLEMENTATION -> FINAL_REVIEW
-> MERGE_AUTHORIZED -> MERGED
~~~

Later docs-only product candidates may use:

~~~text
GATE_DRAFT -> GATE_REVIEW -> MERGE_AUTHORIZED -> MERGED (then active=false)
~~~

Codex must generate a current Review Bundle before each review request and
validate it with `--require-clean --require-bundle`. The C2C execution record
must identify the task, candidate SHA, changed-file count and checks. ChatGPT
must independently inspect state, diff, relevant documents, tests and Bundle
through the read-only bridge. Exact-head GitHub Actions is required before
the process-hardening candidate can be merged.

## Go / No-Go

Go for this Gate Draft requires exact docs-only scope, a clean working tree,
passing local Gate checks, a current Bundle and an independent Review that
accepts the proposed invariants. It does not mean the validator implementation
is complete. Any ambiguity between `fixed_head` and `docs_review_head`, any
scope escape, or any implied product/merge authorization is No-Go.
