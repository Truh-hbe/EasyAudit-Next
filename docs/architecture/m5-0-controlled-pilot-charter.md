# M5 Controlled Pilot Charter

## Status

This document is the M5 parent charter. It defines the controlled-pilot objective
and boundaries; it does not authorize implementation of M5.1 through M5.5.

The current executable slice is M5.1 and has its own Architecture / Acceptance
Gate, branch, PR, and Codex with ChatGPT review.

## Objective

Move the M4-complete reusable audit platform to a controlled organizational pilot
without introducing a second Product-owned source of business truth.

The pilot must eventually support this operational path:

```text
initialize the system -> configure people -> create a ReviewPlan
-> create either supported ReviewCase -> form and correct a Case team
-> use the existing collaboration flow -> recover from ordinary mistakes
```

Supported exact scenarios for M5 are:

- `process_review@1`
- `compliance_review@1`

## Provisional sequence

1. M5.1 Review Catalog and Scenario Readiness
2. M5.2 Plan-first Planning Surface
3. M5.3 Case Team Planning
4. M5.4 Minimal Pilot Administration
5. M5.5 Controlled Pilot Hardening and Final Evidence

Each slice must create and pass its own Gate before executable work. A 12-week
schedule is planning guidance and never bypasses Gate review.

## Pilot invariants

- Exact `(scenario_key, scenario_version)` resolution is mandatory everywhere.
- The backend remains the authority for authorization and business validation.
- Frontend scenario adapters own presentation and payload construction only.
- No generic or dynamic scenario form/workflow builder is included in M5.
- No new Review domain aggregate is introduced only to compose the Product UI.
- A system administrator does not receive a business-case permission shortcut.
- Organization isolation applies to every catalog, plan, case, member, and admin flow.
- Real PostgreSQL, FastAPI, and browser evidence are required for final pilot proof.

## Explicit non-goals

M5 does not include production deployment, a third scenario, evidence storage,
dashboard redesign, workflow design, email password recovery, MFA, SSO, or a
large design-system rewrite.

## C2C efficiency measures

Record per slice/PR:

- manual context transfers: target `0`;
- implementation-review iterations: median no more than `2`;
- scope drift reaching Final Review: target `0`;
- P1 issues first discovered only at Final Review: target `0`;
- CI wiring failures: target `0`;
- active slice elapsed time;
- Codex token use only when reliably exposed by the harness.

## Authority

The outer lifecycle remains:

```text
GATE_DRAFT -> GATE_REVIEW -> IMPLEMENTATION -> FINAL_REVIEW
-> MERGE_AUTHORIZED -> MERGED
```

The inner Codex with ChatGPT loop remains separate. A C2C `DONE` result never
authorizes a phase transition or merge. GitHub exact-head CI is final evidence,
and merge still requires explicit user authorization.
