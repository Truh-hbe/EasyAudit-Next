# Agent Development Workflow — ChatGPT + Codex + GitHub

## Purpose

EasyAudit-Next keeps its existing architecture/acceptance discipline while removing repeated manual transfer of source, diffs, test summaries, SHAs and PR metadata between ChatGPT and Codex.

The workflow has three authorities:

```text
ChatGPT             Codex                    GitHub / Actions
reason / review  <-> execute / generate  <-> canonical repository evidence
```

Codex with ChatGPT (C2C) is a read-only review bridge. It is not a workflow authority and does not weaken any Gate.

## 1. Two-layer state model

### Outer EasyAudit lifecycle

```text
GATE_DRAFT
  -> GATE_REVIEW
  -> IMPLEMENTATION
  -> FINAL_REVIEW
  -> MERGE_AUTHORIZED
  -> MERGED
```

The outer state is stored in `.easyaudit/development-state.json` when `active=true`.

### Inner C2C iteration

```text
INIT -> PLAN -> EXECUTED -> REVIEW -> PLAN | DONE | BLOCKED
```

C2C `DONE` only closes the current inner iteration. It never advances the outer EasyAudit lifecycle by itself.

## 2. Machine-readable development state

At the start of a new milestone slice, Codex updates `.easyaudit/development-state.json` in the initial Gate commit.

Example:

```json
{
  "schema_version": 1,
  "active": true,
  "project": "EasyAudit-Next",
  "milestone": "M5",
  "slice": "M5.1",
  "phase": "GATE_DRAFT",
  "base": {
    "branch": "main",
    "sha": "<verified-main-sha>"
  },
  "work_branch": "codex/m5-1-planning-surface",
  "pr": { "number": 28 },
  "gate_docs": [
    "docs/architecture/m5-1-planning-surface.md",
    "docs/architecture/m5-1-acceptance.md"
  ],
  "scope": {
    "allowed_paths": [
      ".easyaudit/development-state.json",
      "docs/architecture/**"
    ],
    "forbidden_paths": [
      "src/**",
      "web/**",
      "alembic/**",
      ".github/workflows/**"
    ]
  },
  "fixed_head": null,
  "next_allowed_action": "Architecture / Acceptance review"
}
```

When Architecture / Acceptance review passes, Codex changes the outer state to `IMPLEMENTATION` and updates allowed/forbidden scope according to the approved Gate. The Gate itself remains the source of semantic constraints; the JSON file is only the machine-readable routing/enforcement layer.

## 3. Gate check

Run:

```bash
python scripts/easyaudit_gate.py check
```

When `active=true`, the check validates:

- current `BASE...HEAD` changed paths;
- allowed path boundaries;
- forbidden path boundaries;
- required Gate documents;
- fixed-head match when one is frozen;
- expected work branch when a branch name is available.

The check deliberately does not decide architecture correctness. It prevents mechanical Scope drift so review time can focus on architecture and business invariants.

## 4. Review Bundle

Before an implementation or Final Review request, Codex runs:

```bash
python scripts/easyaudit_gate.py bundle
```

The generated `.easyaudit-review/` directory is intentionally ignored by Git and intentionally readable through C2C.

It contains:

```text
.easyaudit-review/
├── gate-proof.json
├── changed-files.txt
├── branch.diff
└── working-tree.diff
```

`branch.diff` is generated from the committed `BASE...HEAD` comparison. This is required because a clean working tree has no useful ordinary `git diff HEAD`, while Final Review must inspect all committed changes in the milestone slice.

`working-tree.diff` separately exposes any uncommitted delta so ChatGPT can detect a review candidate that is not actually fixed/clean.

## 5. Evidence hierarchy

Evidence is intentionally separated into three levels.

### Iteration evidence

Codex runs focused local tests and records the result through C2C execution records. ChatGPT may use `test_status` / `execution_summary` while iterating.

This is fast feedback only.

### Candidate evidence

Before implementation/final review, Codex runs the Gate-relevant local PostgreSQL/API/browser tests and generates the Review Bundle. ChatGPT independently reads the committed diff and relevant source.

### Final evidence

GitHub Actions is the final CI authority. A C2C execution record is never accepted as proof that exact-head CI passed.

The existing CI remains responsible for Ruff, mypy, architecture checks, OpenAPI, Alembic, PostgreSQL tests, frontend checks, mocked browser acceptance and real PostgreSQL + FastAPI browser acceptance as required by the slice.

## 6. Review responsibilities

### ChatGPT

- read development state and Gate docs first;
- inspect `gate-proof.json` and `branch.diff` independently;
- read only relevant source through C2C;
- return architecture/acceptance findings as P1/P2 or PASS;
- never infer merge authorization from C2C `DONE`;
- use GitHub state/CI as canonical final evidence.

### Codex

- never advance the outer phase without the corresponding review decision;
- execute edits/tests/git work;
- keep Gate scope machine-valid;
- generate the Review Bundle before review;
- isolate out-of-scope prerequisites into separate PRs unless the Gate is formally revised;
- push candidates and collect GitHub CI evidence;
- merge only after explicit user authorization and expected-head protection.

### User

The user remains the authority for product direction, acceptance of architectural trade-offs, and final merge authorization.

## 7. Session lifecycle

EasyAudit does **not** use one indefinitely growing ChatGPT C2C conversation for the whole repository.

Default rule:

```text
one milestone slice / PR -> one C2C conversation
```

After merge, the next slice starts a fresh conversation. Context is reconstructed from:

```text
roadmap
+ development-state.json
+ Gate docs
+ repository source
+ git history
```

This reduces stale assumptions from old milestones while preserving reproducibility.

## 8. C2C toolchain policy

The reviewed C2C revision is pinned in `.easyaudit/toolchain.json`.

Automatic self-update is disabled for EasyAudit work. Upgrade only between milestone slices as an explicit tooling change, verify the new bridge, then update the pin.

This keeps the review harness reproducible alongside fixed-head development discipline.

## 9. Sensitive-data boundary

`.c2cignore` excludes credentials, private deployment material, customer data, exports, uploaded evidence storage and other runtime data. Gate docs, source, tests and generated `.easyaudit-review` evidence remain readable.

The bridge is a source-review tool, not a production-data access path.

## 10. Recommended normal slice

```text
User selects slice
  -> Codex creates branch + Draft PR + Gate docs + active development state
  -> Gate check
  -> ChatGPT Architecture / Acceptance Review
  -> state = IMPLEMENTATION
  -> C2C PLAN / Codex execution / focused tests / C2C REVIEW loops
  -> bundle
  -> ChatGPT implementation review
  -> fixes + regressions
  -> state = FINAL_REVIEW + fixed_head
  -> GitHub exact-head CI
  -> bundle + GitHub evidence
  -> ChatGPT Final Review
  -> user merge authorization
  -> expected-head merge
  -> post-merge verification
  -> state rebaselined for next Gate
```

The intended optimization is therefore not fewer correctness checks. It is fewer human-transcribed facts.
