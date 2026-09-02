---
description: Execute a read-only Final Review of one fixed executable candidate
argument-hint: "<PR> <fixed-candidate-SHA>"
---
Review PR `$1` at fixed executable candidate `$2`. Verify trusted predecessors,
BASE...candidate, candidate...control, clean/current Bundle, Acceptance
invariants and exact-head required checks. Report P0/P1/P2 and PASS/NO-GO.
Do not edit, advance state, mark Ready, merge, deploy or access secrets.
