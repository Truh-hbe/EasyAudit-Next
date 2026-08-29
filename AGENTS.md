# EasyAudit-Next Agent Development Contract

This repository is developed and reviewed through Web ChatGPT in the EasyAudit-Next project.

## Roles

- Web ChatGPT / GPT-5.6 sol is the semantic project developer and reviewer. It owns product understanding, architecture, implementation decisions, code semantics, acceptance design, Gate Review, Final Review and release recommendations.
- Local Codex / browser is the workflow driver and execution layer. It starts or reopens the correct Web ChatGPT project conversation, supplies structured repository state, collects responses, applies approved changes, runs local/test/deployment/browser checks when needed, and maintains GitHub evidence.
- GitHub / GitHub Actions is the canonical source for repository content, PR state, commit SHAs, merge state and final CI evidence.

Local Codex and browser must not replace Web ChatGPT's product, architecture or acceptance decisions. They may execute an approved plan and report evidence, but may not silently widen scope or declare a semantic review pass.

## Conversation lifecycle

Each milestone slice or PR has two Web ChatGPT conversations:

- Dev conversation: GPT-5.6 sol develops the solution, plans implementation, defines invariants and directs execution.
- Review conversation: GPT-5.6 sol independently reviews the exact candidate and records P1/P2 findings or PASS.

The local driver starts the appropriate project conversation. The user is not required to copy source, diffs, test logs, SHAs or previous summaries between conversations.

## Outer EasyAudit state machine

The authoritative phase is read from .easyaudit/development-state.json when active=true:

GATE_DRAFT -> GATE_REVIEW -> IMPLEMENTATION -> FINAL_REVIEW -> MERGE_AUTHORIZED -> MERGED

A Web ChatGPT or local driver DONE response only closes the current interaction. It never authorizes a merge or advances the outer phase by itself.

## Web ChatGPT and local driver loop

INIT -> WEB_BOOTSTRAP -> WEB_DEV_OR_REVIEW -> LOCAL_EXECUTION -> WEB_FEEDBACK -> PLAN | REVIEW | DONE | BLOCKED

The local driver must send a structured bootstrap containing the verified state, exact branch/PR/head, Gate documents, scope, latest CI and requested mode. Web ChatGPT must independently read the repository and GitHub evidence rather than trusting the bootstrap as proof.

## Mandatory startup sequence

Before any development or review action:

1. Read AGENTS.md and docs/architecture/project-status.md.
2. Read .easyaudit/development-state.json and its listed Gate documents.
3. Read .easyaudit/review-decision.json when present.
4. Verify main, the active branch, base SHA, PR head and latest GitHub Actions run.
5. Run python scripts/easyaudit_gate.py check when active=true.
6. Report phase and next_allowed_action.
7. Do not perform work belonging to a later outer phase.

If state, GitHub or CI evidence conflicts, stop and reconcile the conflict. Do not ask the user to manually reconstruct facts that can be read from the repository or GitHub.

## Scope discipline

When active=true, changed files must satisfy scope.allowed_paths and must not match scope.forbidden_paths.

- A docs-only Architecture Gate remains docs-only.
- Product implementation requires a passing Gate and an explicit scope transition.
- Out-of-scope prerequisites are isolated in a separately reviewed PR.

## Review and evidence

Web ChatGPT Review reads the exact candidate diff, relevant source, state, Gate documents and GitHub CI. It records the verdict, reviewed head/tree, CI run, P1/P2 findings, scope result and next_allowed_action in .easyaudit/review-decision.json or the approved GitHub review record.

Local test, deployment and browser results are execution evidence. GitHub Actions is final CI authority. No chat response, local prose or driver summary substitutes for exact-head CI.

## Merge

Merge requires a passing Web ChatGPT Final Review, zero open P1/P2 findings, required PostgreSQL/API/browser evidence, green exact-head GitHub Actions, fixed candidate SHA and explicit user authorization.

Use expected-head protection when supported, then verify main, merge parents, tree and PR state.

## Sensitive data

Respect .c2cignore. Never expose credentials, customer exports, uploaded evidence, private deployment material or local secrets through Web ChatGPT or the local driver.