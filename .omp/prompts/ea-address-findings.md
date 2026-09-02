---
description: Revise only the documents or code needed to close one reviewed finding set
argument-hint: "<PR> <review-reference>"
---
For PR `$1`, address only findings in `$2`. First use the typed rollback to the
legal repair phase. Preserve Gate Scope and candidate/control discipline. Run
focused regression plus Gate checks, create a new candidate, then stop for an
independent re-review. Do not authorize or merge.
