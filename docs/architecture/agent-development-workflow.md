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

`fixed_head` has one precise meaning: the last executable candidate that
completed Implementation Review. It is not the commit that happens to contain
the `FINAL_REVIEW` state. In `FINAL_REVIEW`, the candidate HEAD must descend
from `fixed_head`, and the range after `fixed_head` may contain only paths named
by `finalization_allowed_paths` (normally the development state file). This
allows the state transition to be recorded without requiring a commit to know
its own future SHA. Any source, test, CI or configuration change after
`fixed_head` fails the Gate and starts a new implementation review.

### Candidate kinds and docs-only finalization

The process may explicitly distinguish `candidate_kind: executable` from
`candidate_kind: docs-only`. An executable candidate keeps the `fixed_head`
contract above. A docs-only candidate has no executable fixed head and instead
uses `docs_review_head` after its document candidate has been reviewed.

The docs-only exception is process-owned and must not be created merely by
adding paths to a milestone's `allowed_paths`. The validator implementation
must require that the complete docs-only change set is a subset of the
process-owned positive allowlist `.easyaudit/development-state.json` and
`docs/**`; the milestone scope may only narrow that set. It must also require
that finalization paths remain a subset of the state file, reject
`IMPLEMENTATION` and `FINAL_REVIEW`, and reject an active `MERGED` state. A
merged docs-only state is closed with `active=false`.

The docs-only lifecycle is therefore:

```text
GATE_DRAFT -> GATE_REVIEW -> MERGE_AUTHORIZED -> MERGED (then active=false)
```

Only the separately reviewed process-hardening implementation may add these
validator rules and their tests. Until that implementation Gate passes, a
process-hardening branch remains an ordinary executable candidate and must
follow the full outer lifecycle.

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
- a non-empty, resolvable fixed head in `FINAL_REVIEW`;
- fixed-head ancestry and finalization-only changes in `FINAL_REVIEW`;
- expected work branch when a branch name is available.

The check deliberately does not decide architecture correctness. It prevents mechanical Scope drift so review time can focus on architecture and business invariants.

## 4. Review Bundle

Before an implementation or Final Review request, Codex runs:

```bash
python scripts/easyaudit_gate.py bundle
python scripts/easyaudit_gate.py check --require-clean --require-bundle
```

The second command is mandatory for Final Review. It rejects a missing or
malformed bundle and verifies that `gate-proof.json` and every canonical
artifact match freshly rebuilt current HEAD, tree, base, branch, changed paths,
Gate phase, state fingerprint and working-tree evidence. Missing, modified,
stale or mixed-generation artifacts are invalid. Bundle generation writes the
diff artifacts first and `gate-proof.json` last; the proof is the completion
marker. If anything changes after bundle generation, regenerate the bundle
before requesting review.

The generated `.easyaudit-review/` directory is intentionally ignored by Git and intentionally readable through C2C.

It contains:

```text
.easyaudit-review/
├── gate-proof.json
├── changed-files.txt
├── branch.diff
├── candidate.diff
├── control.diff
└── working-tree.diff
```

`branch.diff` is generated from the committed `BASE...HEAD` comparison. This is required because a clean working tree has no useful ordinary `git diff HEAD`, while Final Review must inspect all committed changes in the milestone slice.

For Final Review, `candidate.diff` is the canonical full-slice diff
`BASE...fixed_head`; `control.diff` is the canonical metadata-only delta
`fixed_head..bundle_head`. `working-tree.diff` is the uncommitted delta. The
proof records these refs so a reviewer never has to infer which commit a diff
represents from its filename alone.

`working-tree.diff` separately exposes any uncommitted delta so ChatGPT can detect a review candidate that is not actually fixed/clean.

## 5. Evidence hierarchy

Evidence is intentionally separated into three levels.

### Iteration evidence

Codex runs focused local tests and records the result through C2C execution records. ChatGPT may use `test_status` / `execution_summary` while iterating.

This is fast feedback only.

### Candidate evidence

Before implementation/final review, Codex runs the Gate-relevant local PostgreSQL/API/browser tests and generates the Review Bundle. ChatGPT independently reads the committed diff and relevant source.

PostgreSQL tests are opt-in outside CI. A skipped PostgreSQL suite is not
candidate evidence and must be reported as incomplete. When a local PostgreSQL
instance is available, use the same switch as CI:

```bash
EASYAUDIT_RUN_POSTGRES_TESTS=1 python3 -m pytest
```

If PostgreSQL is unavailable, keep the local result as fast feedback only and
rely on the exact-head GitHub run for final evidence. Do not summarize skipped
tests as passed tests.

### Final evidence

GitHub Actions is the final CI authority. A C2C execution record is never accepted as proof that exact-head CI passed.

The existing CI remains responsible for Ruff, mypy, architecture checks, OpenAPI, Alembic, PostgreSQL tests, frontend checks, mocked browser acceptance and real PostgreSQL + FastAPI browser acceptance as required by the slice.

## 6. Review responsibilities

### ChatGPT

- read development state and Gate docs first;
- inspect `gate-proof.json`, `candidate.diff`, `control.diff` and
  `working-tree.diff` independently; `branch.diff` is convenience evidence,
  not the canonical Final Review diff;
- read only relevant source through C2C;
- return architecture/acceptance findings as P1/P2 or PASS;
- never infer merge authorization from C2C `DONE`;
- use GitHub state/CI as canonical final evidence.

### Codex

- never advance the outer phase without the corresponding review decision;
- execute edits/tests/git work;
- keep Gate scope machine-valid;
- generate the Review Bundle before review;
- record each completed execution immediately through the C2C execution-record
  path; an unrecorded run is not candidate evidence;
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
  -> state = FINAL_REVIEW + fixed_head (executable review head)
  -> finalization-only state commit
  -> bundle + check --require-clean --require-bundle
  -> GitHub exact-head CI
  -> GitHub evidence attached to the actual current PR/control HEAD
  -> ChatGPT Final Review
  -> user merge authorization
  -> expected-head merge
  -> post-merge verification
  -> state rebaselined for next Gate
```

The intended optimization is therefore not fewer correctness checks. It is fewer human-transcribed facts.
