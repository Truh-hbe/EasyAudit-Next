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
- Require a non-empty, resolvable `fixed_head` in `FINAL_REVIEW`.
- Permit only explicitly allowed finalization metadata commits after the fixed
  head; source, tests, CI and configuration changes must fail the Gate.
- Make the Gate verify that a requested Review Bundle matches the current
  commit, state, scope and working-tree status.
- Add focused tooling tests for missing, invalid, stale and valid evidence.
- Document a candidate-test command that makes PostgreSQL opt-in status
  visible instead of silently treating skipped tests as full evidence.

## Out of scope

- No product source, frontend, database migration or API behavior changes.
- No change to the M5.1 branch or PR #30.
- No merge authorization.
- No new general-purpose scenario builder, CI provider or C2C service.

## Acceptance criteria

1. `FINAL_REVIEW` fails when `fixed_head` is empty, unknown, not an ancestor
   of the candidate head, or is followed by any non-finalization file.
2. A finalization-only state commit passes when it descends from the reviewed
   executable head.
3. GitHub pull-request merge-ref checks use the actual PR head for fixed-head
   validation and never mistake the synthetic merge commit for the candidate.
4. `check --require-bundle --require-clean` fails for a missing, malformed,
   stale, dirty or scope-failing Review Bundle.
5. The bundle records the state fingerprint and fixed-head evidence used by the
   Gate.
6. Focused tooling tests cover all cases above and pass with the repository's
   standard test command.
7. The workflow document explicitly distinguishes C2C iteration evidence,
   candidate evidence and exact-head GitHub evidence.

## Slice protocol

`GATE_DRAFT -> GATE_REVIEW -> IMPLEMENTATION -> FINAL_REVIEW ->
MERGE_AUTHORIZED -> MERGED`

The implementation phase begins only after the architecture/acceptance review
of this document. The final state transition is metadata-only and must point
back to the implementation-reviewed executable head through `fixed_head`.
