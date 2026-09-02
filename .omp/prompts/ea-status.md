---
description: Inspect the current EasyAudit control-plane state without mutation
---
Call `ea_status`. Verify state, branch, HEAD, base, lease, policy hash,
predecessors, working tree and allowed next action. Treat remote claims as stale
unless independently verified. Do not modify files or advance state.
