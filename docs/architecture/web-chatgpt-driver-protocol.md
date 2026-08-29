# Web ChatGPT Development and Review Driver Protocol

## Purpose

EasyAudit-Next is developed and reviewed through Web ChatGPT in the project. GPT-5.6 sol is the semantic developer and reviewer. Local Codex and the browser are the driver and execution layer: they start the right project conversation, provide machine-readable context, collect the response, apply approved changes, run tests and perform deployment/browser checks when needed.

The local driver must reduce manual transcription. It must never replace Web ChatGPT's architecture, product or acceptance decisions.

## Conversation roles

Every milestone slice has two Web ChatGPT conversations:

- Dev conversation: GPT-5.6 sol owns the implementation plan, code semantics, invariants, acceptance design and iteration decisions.
- Review conversation: GPT-5.6 sol independently reviews the exact candidate. It must not treat the Dev conversation's conclusion as evidence.

A new Web ChatGPT conversation is a normal recovery point. The user does not need to paste previous summaries, source, diffs, test logs or SHAs.

## Local driver loop

1. Read project status, AGENTS.md, the active development state, Gate documents and GitHub PR/CI.
2. Classify the requested operation as Status, Dev, Gate Review or Final Review.
3. Open or reuse the correct Web ChatGPT project conversation.
4. Send a structured bootstrap containing the verified state, exact PR/head, required documents, constraints and next_allowed_action.
5. Let Web ChatGPT produce the plan, review finding or decision.
6. Apply only the approved implementation changes and run the requested local/deployment/browser checks.
7. Return structured execution evidence to Web ChatGPT and update GitHub/state records.
8. Stop when the state machine or Web ChatGPT decision says review, authorization or user input is required.

## Web ChatGPT bootstrap contract

Every bootstrap must identify:

- project and milestone/slice;
- outer phase and next_allowed_action;
- base branch and exact base SHA;
- active PR and exact candidate head;
- Gate/Acceptance documents;
- changed-file scope and forbidden paths;
- latest GitHub Actions result;
- local test or deployment evidence, if any;
- the requested mode: Dev, Gate Review or Final Review.

Web ChatGPT must read the repository and GitHub evidence itself. A driver summary is a pointer, not a substitute for independent reading.

## Review decision record

Gate and Final Review decisions must be recorded with:

- verdict: PASS or FAIL;
- reviewed head SHA and tree;
- CI run and conclusion;
- P1 and P2 findings;
- scope result;
- next_allowed_action;
- reviewer mode and timestamp.

Only a recorded PASS can advance the outer state. A chat response such as DONE is not a review record and does not authorize merge.

## Capability boundary

Web ChatGPT is the project brain. The local Codex/browser may execute approved edits, shell/test/deployment commands, browser acceptance, Git operations and GitHub maintenance. GitHub and GitHub Actions remain the canonical source for code, PR, SHA, merge and final CI facts.

If local execution or browser access is unavailable, the driver reports the blocker to Web ChatGPT. It does not invent a successful result or silently change the semantic plan.