# Web ChatGPT Development Workflow

## Purpose

EasyAudit-Next uses Web ChatGPT / GPT-5.6 sol as the project developer and independent reviewer. Local Codex and the browser drive the Web ChatGPT project conversations and execute the approved work. GitHub and GitHub Actions preserve the authoritative repository and CI evidence.

The purpose of the workflow is to remove manual result transcription while keeping semantic development and review inside Web ChatGPT.

## 1. Responsibility model

Web ChatGPT / GPT-5.6 sol:

- understands the product and repository;
- defines architecture, scope, invariants and acceptance;
- plans and directs implementation;
- performs independent Gate, implementation and Final Review;
- records review decisions and next allowed actions.

Local Codex / browser:

- starts or reopens the correct Web ChatGPT project conversation;
- prepares a verified structured bootstrap from repository and GitHub state;
- drives Dev and Review prompts without manual user relay;
- applies Web ChatGPT-approved changes;
- runs local, deployment and browser acceptance when required;
- reports structured evidence back to Web ChatGPT;
- maintains branches, PRs, CI checks and state records.

GitHub / GitHub Actions:

- stores the code and machine-readable records;
- provides PR, commit, branch and merge facts;
- provides exact-head CI and final acceptance evidence.

## 2. Conversation modes

Every new project conversation is classified into one mode:

- Status: recover and report the current state only.
- Dev: Web ChatGPT develops the selected slice and directs local execution.
- Gate Review: Web ChatGPT independently reviews the architecture/acceptance candidate.
- Final Review: Web ChatGPT independently reviews the implementation candidate and exact evidence.

The local driver should open a fresh Review conversation for Gate Review and Final Review. A Dev conversation's conclusion is never the Review conversation's evidence.

## 3. New conversation bootstrap

The local driver first reads:

1. AGENTS.md.
2. docs/architecture/project-status.md.
3. .easyaudit/development-state.json.
4. Every Gate document listed by the state.
5. .easyaudit/review-decision.json when present.
6. Current main, active branch, PR, candidate SHA/tree and latest GitHub Actions.

It then sends Web ChatGPT a structured bootstrap with project, milestone, slice, phase, requested mode, base SHA, candidate head, scope, forbidden paths, CI result and next_allowed_action.

Web ChatGPT independently reads the cited repository and GitHub resources. The bootstrap is routing context, not proof.

## 4. Development loop

User selects or confirms the slice.

Local driver -> opens Web ChatGPT Dev conversation -> Web ChatGPT reads state and source -> Web ChatGPT writes plan and acceptance -> local driver applies approved changes -> local driver runs tests/deployment/browser checks -> local driver returns structured evidence -> Web ChatGPT reviews the result and decides the next iteration.

Semantic scope changes, new domain truth, lifecycle, permission, persistence, authorization or concurrency decisions remain Web ChatGPT decisions.

## 5. Gate Review loop

Local driver opens a fresh Web ChatGPT Review conversation.

Web ChatGPT reads the exact candidate diff, current source, Gate docs, state file, review record and GitHub CI. It returns PASS or FAIL with P1/P2 findings and records:

- verdict;
- reviewed head and tree;
- CI run and conclusion;
- changed-file scope result;
- P1 and P2 findings;
- next_allowed_action;
- reviewer mode and timestamp.

Only a recorded PASS advances the outer state. A chat DONE is not a review decision.

## 6. Execution and deployment evidence

Local Codex may execute approved code changes, shell commands, migrations, local service startup, deployment checks and authenticated browser journeys. It reports exact commands, results, logs and URLs back to Web ChatGPT.

Web ChatGPT decides whether the evidence satisfies the Gate. GitHub Actions remains the final authority for the reviewed candidate.

## 7. Outer state machine

GATE_DRAFT -> GATE_REVIEW -> IMPLEMENTATION -> FINAL_REVIEW -> MERGE_AUTHORIZED -> MERGED

State changes are made only after the corresponding Web ChatGPT decision and are checked by the repository Gate tooling.

## 8. Persistence across new conversations

The durable context is:

project instructions + AGENTS.md + project-status.md + development-state.json + Gate documents + review-decision.json + GitHub PR/CI.

Previous chat history is useful context but is not required for recovery. A new Web ChatGPT conversation must be able to continue from the durable records without user transcription.

## 9. Merge rule

Merge requires Web ChatGPT Final Review PASS, zero open P1/P2 findings, required local/deployment/browser evidence, exact-head GitHub Actions success, fixed SHA and explicit user authorization.