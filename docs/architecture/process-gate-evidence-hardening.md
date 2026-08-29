# M5 Process Gate and Evidence Hardening

## Purpose

This is a separate workflow/tooling slice created after the M5.1 review exposed
three process weaknesses:

1. `FINAL_REVIEW` could pass with an empty `fixed_head`.
2. A final-review state commit could make the review head ambiguous or
   self-referential.
3. A Review Bundle could be stale while still being presented as current
   evidence.

The slice makes those conditions machine-checkable and documents the minimum
candidate-evidence protocol. It does not change M5.1 product behavior and does
not authorize M5.2 or later product work.

## In scope

- Give `fixed_head` one precise meaning: the implementation-reviewed executable
  commit.
- Distinguish the immutable candidate head from later control/state heads:
  `C = fixed_head`, while `S/R/M` may carry only approved process metadata.
- Require a non-empty, resolvable `fixed_head` in `FINAL_REVIEW`.
- Require the same invariant in `MERGE_AUTHORIZED`.
- Permit only explicitly allowed finalization metadata commits after the fixed
  head; source, tests, CI and configuration changes must fail the Gate.
- Make the Gate verify that a requested Review Bundle matches the current
  commit, state, scope and working-tree status.
- Separate candidate/full-slice evidence (`BASE...C`) from control delta
  evidence (`C..bundle_head`) and uncommitted working-tree evidence.
- Add focused tooling tests for missing, invalid, stale and valid evidence.
- Document a candidate-test command that makes PostgreSQL opt-in status
  visible instead of silently treating skipped tests as full evidence.

## Out of scope

- No product source, frontend, database migration or API behavior changes.
- No change to the M5.1 branch or PR #30.
- No merge authorization.
- No new general-purpose scenario builder, CI provider or C2C service.

## Acceptance criteria

1. `GATE_DRAFT` and `IMPLEMENTATION` still allow an empty `fixed_head`.
2. `FINAL_REVIEW` and `MERGE_AUTHORIZED` fail when `fixed_head` is empty,
   unknown or not an ancestor of the current control head.
3. A real candidate commit `C` followed by a state-only commit `S` passes, but
   a source/test/migration/CI commit after `C` fails.
4. GitHub pull-request merge-ref checks use the actual PR head for fixed-head
   validation and never mistake the synthetic merge commit for the candidate.
5. `check --require-bundle --require-clean` fails for a missing, malformed,
   stale, dirty or scope-failing Review Bundle.
6. The bundle records the state fingerprint, immutable candidate head, current
   control head and the evidence refs used by the Gate.
7. Focused tooling tests use a real temporary Git topology for `C -> S` and
   cover the synthetic GitHub merge-ref case as well.
8. The workflow document explicitly distinguishes C2C iteration evidence,
   candidate evidence and exact-head GitHub evidence.

## Slice protocol

`GATE_DRAFT -> GATE_REVIEW -> IMPLEMENTATION -> FINAL_REVIEW ->
MERGE_AUTHORIZED -> MERGED`

The implementation phase begins only after the architecture/acceptance review
of this document. The final state transition is metadata-only and must point
back to the implementation-reviewed executable head through `fixed_head`.
