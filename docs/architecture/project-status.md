# EasyAudit-Next Project Status

Last verified: 2026-08-29

## Current snapshot

- Repository main baseline: 90d5a1a6ba447d59f0941e85890c4eee8b00aee1.
- Product M4 completion baseline: 939eae3d96874e24688683777f8757c5170eb975.
- M4 Second Scenario Validation is complete. No artificial M4.2 is required.
- Development workflow foundation is merged through PR #28.
- Current slice: M5.1 ReviewPlan Planning Surface Architecture / Acceptance Gate.
- Current Gate branch: codex/m5-1-reviewplan-planning-gate.

## Completed product milestones

- M0 Bootstrap.
- M1 Platform Foundation.
- M2 Process Review.
- M3 Collaboration and Management.
- M3.5 Product Surface.
- M4 Second Scenario Validation using compliance_review@1.

## Persistent startup contract

Every new project conversation must reconstruct context from repository state before relying on prior chat history:

1. Read AGENTS.md and this file.
2. Read .easyaudit/development-state.json.
3. Read every Gate document listed by the state file.
4. Verify main, the active branch, the base SHA, the PR head and the latest GitHub Actions run.
5. Run the Gate check when active=true.
6. Report the current phase and next_allowed_action before changing files.

An inconsistent state, missing Gate document, moved fixed head or stale CI result stops work until reconciled.

## Authority model

- ChatGPT: architecture, acceptance, semantic implementation review and release recommendation.
- Codex: workspace execution, tests, Git operations, evidence generation and PR maintenance.
- GitHub / GitHub Actions: canonical repository, SHA, merge and final CI evidence.
- C2C or chat DONE: iteration completion only; never merge authorization.
- User: product direction, trade-off approval and final merge authorization.

## Current next action

The M5.1 Gate must first receive an independent Architecture / Acceptance review. No executable product work is authorized while the state phase is GATE_DRAFT or GATE_REVIEW.

After a passing Gate, the state file may move to IMPLEMENTATION and the scope may be widened explicitly. The first implementation target is the ReviewPlan planning surface; later M5 slices must not be started implicitly.

## Recovery rule

A fresh conversation may continue the active slice by reading this status, the state file, the Gate documents, GitHub and the relevant source. It must not require the user to paste a previous conversation or manually transcribe SHAs and test output.