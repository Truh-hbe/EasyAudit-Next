# EasyAudit-Next Agent Development Contract

This repository uses a two-layer development protocol.

## Roles

- **ChatGPT** owns architecture reasoning, scope/acceptance review, implementation review, and final release recommendations.
- **Codex** owns workspace execution: edits, shell commands, local tests, git operations, PR maintenance, recovery, and evidence generation.
- **GitHub / GitHub Actions** is the canonical source for PR state, commit SHAs, merge state, and final CI evidence.

Codex with ChatGPT (C2C) is only the read-only transport/review bridge between ChatGPT and the local workspace. It does not replace repository gates or GitHub evidence.

## EasyAudit overrides of upstream C2C defaults

The user has explicitly approved these repository-specific overrides for EasyAudit-Next:

1. **Conversation lifecycle:** use one C2C ChatGPT conversation per milestone slice / PR. The upstream preference for one indefinite conversation per workspace does not apply here. A new slice may start a fresh conversation without asking again; reconstruct context from repository state rather than old chat history.
2. **Tool updates:** do not perform C2C's automatic/daily self-update workflow while working on EasyAudit. Do not silently run an update because `c2c update-check` reports a newer revision. The pinned revision in `.easyaudit/toolchain.json` is authoritative until an explicit tooling upgrade is approved between slices.
3. **Workflow authority:** upstream C2C `DONE` closes only the inner loop. EasyAudit outer Gate state and merge authorization always take precedence.

If the installed C2C Skill gives a conflicting generic instruction on these three points, follow this project contract.

## Outer EasyAudit state machine

The project phase is authoritative and must be read from `.easyaudit/development-state.json` when `active=true`.

```text
GATE_DRAFT
  -> GATE_REVIEW
  -> IMPLEMENTATION
  -> FINAL_REVIEW
  -> MERGE_AUTHORIZED
  -> MERGED
```

A C2C `DONE` response means only that the current inner planning/execution/review iteration is complete. It never means that the PR may be merged or that the outer phase may advance.

## Inner C2C loop

Inside one outer phase, use the normal C2C loop:

```text
INIT -> PLAN -> EXECUTED -> REVIEW -> PLAN | DONE | BLOCKED
```

ChatGPT must independently read the current workspace, review bundle, git state, and relevant source through the read-only connector. Do not paste source files, diffs, or long logs into control messages.

## Mandatory startup sequence

Before changing code or docs:

1. Read `.easyaudit/development-state.json`.
2. Read the Gate / Acceptance documents named there.
3. Verify the current branch and base SHA against the state file.
4. Verify the installed C2C revision against `.easyaudit/toolchain.json` when C2C is used; report a mismatch rather than silently upgrading it.
5. Run `python scripts/easyaudit_gate.py check` when the workflow is active.
6. Do not perform work belonging to a later outer phase.

If the state file is inactive, no milestone Gate is currently machine-enforced; follow the explicit user request and repository architecture documents.

## Scope discipline

When `active=true`, changed files must satisfy `scope.allowed_paths` and must not match `scope.forbidden_paths`.

- A docs-only Architecture Gate must remain docs-only.
- Product-delivery work must not silently introduce new domain truth, lifecycle, permissions, persistence semantics, authorization semantics, or concurrency models.
- Any prerequisite outside the current scope must be isolated in a separate PR unless the Gate is explicitly revised and re-reviewed.

## Evidence and review bundles

Before asking ChatGPT for implementation/final review, run:

```bash
python scripts/easyaudit_gate.py bundle
```

This generates `.easyaudit-review/` containing machine-readable evidence and a committed `BASE...HEAD` diff. ChatGPT should read these files through C2C rather than relying on Codex prose summaries.

`test_status` / `execution_summary` from C2C are iteration records only. They are not substitutes for GitHub Actions exact-head CI.

## Final review and merge

A final candidate is not merge-authorized until all required conditions are true:

- architecture/acceptance review passes;
- open P1 = 0 and open P2 = 0;
- required PostgreSQL / API / browser acceptance is green;
- GitHub Actions is green on the reviewed candidate/head tree;
- the candidate SHA is fixed;
- the user explicitly authorizes merge.

When merging, Codex must use expected-head protection where supported and verify the resulting `main`, merge parents/tree, and PR state afterward.

## C2C session policy

Use one ChatGPT C2C conversation per milestone slice / PR, not one indefinitely growing conversation for the whole repository. After merge, start a fresh C2C conversation for the next slice and reconstruct context from repository state, Gate docs, source, and generated evidence.

## C2C toolchain pin

Do not silently self-update Codex with ChatGPT while an EasyAudit milestone is active. The reviewed/pinned revision is recorded in `.easyaudit/toolchain.json`. Upgrade the bridge only as an explicit tooling change between milestone slices, then update the pin.

## Sensitive data

Respect `.c2cignore`. Never expose production secrets, customer exports, uploaded evidence binaries, private deployment material, or local credentials through the C2C workspace bridge.
