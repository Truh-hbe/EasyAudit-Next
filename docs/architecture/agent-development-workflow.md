# Agent Development Workflow — ChatGPT + OMP Agent + GitHub

## Purpose

EasyAudit-Next separates reasoning, local execution, repository evidence and
human authority:

```text
ChatGPT             OMP Agent                 GitHub / Actions
architecture/review <-> execute/verify/control <-> canonical remote evidence
                              |
                              v
                    Human Maintainer authority
```

Conversation memory is never a workflow authority. The machine state,
trusted workflow policy, reviewed Gate, Git ancestry, exact-head CI and current
human action form the authority chain.

## 1. Outer lifecycle

```text
GATE_DRAFT
  -> GATE_REVIEW
  -> IMPLEMENTATION
  -> FINAL_REVIEW
  -> MERGE_AUTHORIZED
  -> MERGED
```

The current Slice is stored in `.easyaudit/development-state.json` while
`active=true`. The versioned trust policy is
`.easyaudit/workflow-policy.json`.

`fixed_head` identifies the reviewed executable candidate. `docs_review_head`
identifies a reviewed docs-only candidate. Later control commits may change
only `finalization_allowed_paths`, normally the state file.

## 2. Per-turn OMP protocol

Every request is classified before tools run:

```text
READ_ONLY | PLAN | MUTATE | REVIEW | MERGE | DEPLOY
```

- READ_ONLY verifies external claims rather than trusting prose.
- PLAN verifies machine predecessors and Roadmap direction.
- MUTATE requires the single-writer lease, passing preflight and exact Scope.
- REVIEW targets a fixed candidate with a clean/current Bundle.
- MERGE requires MERGE_AUTHORIZED, trusted exact-head checks, expected-head
  protection and a one-shot current human confirmation.
- DEPLOY requires a dedicated environment Gate and current operator action.

The project OMP Extension injects a fresh status snapshot before every Agent
turn and after startup/reload/session replacement/compaction. Historical chat
and compaction summaries cannot mint phase, evidence or authorization.

## 3. Single-writer workspace

Mutation-capable OMP sessions must start through:

```bash
python3 scripts/easyaudit_agent.py launch --
```

The launcher explicitly loads the project Extension and requires a session-start activation proof. Direct `omp`, `--no-extensions`, disabled/import-failing Extensions, RPC, JSON and print sessions are read-only NO-GO.

The OMP control plane stores a Git-ignored writer lease under `.easyaudit/runtime/`. The lease binds repository, stable OMP Session identity, OMP host process PID, host and a unique generation nonce. Short-lived Python helpers receive that stable owner explicitly and never use their own PID as the OMP owner.

- Only one Session may own writer mode.
- Other Sessions remain read-only.
- Heartbeat/release/takeover compare owner + generation.
- A live owner is never silently preempted.
- Stale takeover requires dead-owner evidence, timeout and explicit human
  confirmation.
- Without a writer lease, all model-facing shell and mutating tools are
  blocked; only dedicated status/diff/verify tools remain.

## 4. Protected policy roots

These files cannot be changed through generic edit/write/shell:

```text
.easyaudit/development-state.json
.easyaudit/workflow-policy.json
```

State changes use a typed old-state → proposed-state adapter. It validates
adjacent phase movement, Scope non-escalation, candidate ancestry, clean Bundle,
trusted predecessors and target-phase remote evidence before atomic write.

Workflow policy changes use a separate reviewed policy-seed PR. A candidate
policy never authorizes itself or the validator/CI that consumes it.

## 5. Safe command surface

Arbitrary model shell is disabled during active Gates. OMP uses versioned
`ea_exec` argv profiles for Gate checks, evidence generation, tests and bounded
Git operations. Unknown profiles, shell composition and protected-root writes
are refused.

TUI `!cmd` uses the `user_bash` guard. An RPC host must prove its direct bash
surface is disabled or equivalently guarded. JSON/print and unverified RPC
modes are read-only NO-GO for mutation, transition, merge and deploy.

## 6. Machine predecessor enforcement

Roadmap prose explains dependencies but does not authorize them. The trusted
workflow policy maps Slice identifiers to predecessor Slice identifiers.

For each predecessor, OMP finds a trusted-main state commit containing:

```text
slice == predecessor
phase == MERGED
active == false
```

That completion commit must be an ancestor of both Slice base and working HEAD.
Missing or side-branch completion blocks PLAN, MUTATE, FINAL_REVIEW and merge.

## 7. Evidence hierarchy

### Local iteration evidence

Focused tests are fast feedback only.

### Candidate evidence

Before Review:

```bash
python3 scripts/easyaudit_gate.py bundle
python3 scripts/easyaudit_gate.py check --require-clean --require-bundle
```

The Bundle separates:

```text
BASE...candidate
candidate...control
uncommitted working tree
```

### Final evidence

GitHub exact-head CI is authoritative. Required check identities come from
branch rulesets or the trusted versioned policy contract. Empty, missing,
pending, failed, cancelled, unexpectedly skipped or head-mismatched checks are
NO-GO.

## 8. External ChatGPT and connector evidence

ChatGPT may write through its GitHub Connector and perform independent Review.
Its returned SHA, PR, CI and merge statements remain unverified until OMP reads
Git/GitHub directly.

Connector fallback order:

```text
ChatGPT GitHub Connector
  -> OMP gh CLI mechanical action
  -> human GitHub UI
```

Fallback changes only execution channel. It never grants review, merge,
deployment, secret or traffic authority.

## 9. Review evidence and human authorization

An independent PASS must be a structured immutable GitHub comment/review reference bound to PR, fixed candidate, result and P0/P1/P2 counts. A free-form `PASS` string is not evidence. MERGE_AUTHORIZED verifies the reference, current local/control head, remote PR head and candidate-only finalization chain.

A merge/deploy grant is created only by a current blocking human UI challenge
that displays exact repository, action, PR/environment, head/release and a
random nonce.

The grant:

- exists only in memory;
- is bound to one tool invocation and exact action;
- is consumed on success/failure/cancel/timeout;
- is not inherited by new/resume/fork/clone/reload/compaction/restart;
- cannot be created by Agent text, state, history, ChatGPT or an injected
  message.

## 10. Prompt orchestration

Project templates under `.omp/prompts/` advance at most one outer transition.
Each names exact refs, allowed and prohibited actions, required evidence and a
stop condition. `/ea-next` generates a prompt only; it does not send it,
change state, authorize or merge.

## 11. Normal Slice

```text
human selects and scopes Slice
  -> machine predecessor check
  -> branch + Draft Gate PR
  -> Gate Review
  -> typed IMPLEMENTATION transition
  -> OMP edits + focused tests
  -> Bundle + fixed candidate
  -> FINAL_REVIEW
  -> exact-head required CI
  -> independent Review PASS
  -> current one-shot human authorization
  -> expected-head merge
  -> verify remote main is the exact merge commit before state publication
  -> CAS-protected post-merge verification/rebaseline
```

At any failure, return to the legal repair phase, clear invalid candidate references, record a bounded reason, fix and re-prove. If GitHub merge succeeds but rebaseline cannot safely proceed, report `REMOTE_MERGED_REBASELINE_PENDING` with the exact merge commit and use the human-confirmed idempotent recovery tool. Never weaken Acceptance to obtain green CI.

## 12. Sensitive data

Control snapshots, leases, logs, prompts and Bundles must not expose passwords,
cookies, tokens, credentials, customer exports, Evidence binaries, private
keys or secret values. Lease metadata contains only bounded process/session
identity. Errors report a bounded class/reason, not raw sensitive input.
