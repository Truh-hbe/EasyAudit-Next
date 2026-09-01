---
name: easyaudit-control-plane
description: Enforces EasyAudit-Next milestone state, scope, local execution, GitHub evidence verification, single-writer coordination, connector fallback and phase-specific prompt orchestration. Use for every planning, mutation, review, merge, deployment, recovery or "continue" request in the EasyAudit-Next repository.
tags: [easyaudit, workflow, governance]
---

# EasyAudit OMP Agent Control Plane

Use this playbook together with the project Extension and repository Gate. The
Skill explains the workflow; it does not replace tool guards, CI or human
authorization.

## Start every task

1. Run `/ea-status` or call `ea_status`.
2. Read `.easyaudit/development-state.json` and the named Gate documents.
3. Confirm branch, HEAD, base, phase, working-tree state and writer lease.
4. Check `.easyaudit/workflow-policy.json` predecessor evidence.
5. Treat external ChatGPT/GitHub prose as unverified until `ea_verify` succeeds.
6. Stop when the state says the requested work belongs to a later phase.

## Classify the request

- `READ_ONLY`: no writer lease required; still verify external claims.
- `PLAN`: verify machine predecessors before proposing a route.
- `MUTATE`: require writer lease, passing preflight and exact Gate scope.
- `REVIEW`: review the fixed candidate, not a floating PR head.
- `MERGE`: require MERGE_AUTHORIZED, trusted required checks, expected head and
  one current human UI confirmation.
- `DEPLOY`: require a dedicated environment Gate and current operator
  confirmation; otherwise stop.

## Candidate discipline

```text
C = fixed_head or docs_review_head
S = state-only control head
W = uncommitted working tree
```

- Candidate changes after `C` are forbidden except finalization state.
- FINAL_REVIEW and MERGE_AUTHORIZED require a clean working tree and current
  Review Bundle.
- A failed CI run invalidates readiness; return to the appropriate repair phase.
- Never weaken an Acceptance assertion merely to make CI green.

## Safe execution

- Use built-in edit/write only for paths permitted by the active Gate.
- State and workflow policy are protected roots; use typed control commands.
- Arbitrary model shell is disabled during an active Gate. Use `ea_exec`
  profiles.
- Without a writer lease, remain read-only. Never take over a live lease.
- Use `/ea-preflight` before asking for Review or authorization.

## GitHub evidence

Verify PR number, base/head SHA, Draft/Ready state, changed paths, checks and
merge state directly. Required check identities come from the trusted base
policy. Missing, empty, stale, pending, failed, cancelled or mismatched evidence
is NO-GO.

Connector fallback order:

```text
web ChatGPT GitHub Connector
  -> local gh CLI mechanical operation
  -> human GitHub UI
```

Fallback changes only the execution channel. It never grants review, merge,
deploy, secret or traffic authority.

## Prompt orchestration

Use the project `ea-*` prompt templates. One prompt advances at most one outer
state transition. Every prompt names exact refs, allowed actions, prohibited
actions, required evidence and a stop condition.

## Session and compaction recovery

After startup, reload, new/resume/fork/clone, compaction or model change, rerun
`/ea-status`. Dynamic status is authoritative over conversation summaries.

## Stop conditions

Stop immediately when any of these is true:

- policy or state cannot be parsed;
- writer lease is owned by another Session;
- branch/base/HEAD does not match state;
- predecessor completion is absent from trusted main ancestry;
- requested path is outside Scope;
- candidate/control relation is invalid;
- working tree is dirty in Final Review;
- required remote evidence is unavailable;
- current human authorization is absent;
- the request belongs to deployment, secrets, traffic or a later Slice.

Read the complete architecture and acceptance contracts at:

- `../../../docs/architecture/process-omp-agent-control-plane.md`
- `../../../docs/architecture/process-omp-agent-control-plane-acceptance.md`
