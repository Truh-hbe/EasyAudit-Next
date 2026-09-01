---
description: Reverify one already authorized EasyAudit PR before a one-shot merge action
argument-hint: "<PR> <expected-head-SHA>"
---
For PR `$1`, verify phase is MERGE_AUTHORIZED, expected head is `$2`, candidate
and control are valid, required checks from trusted base policy are all green,
and current human confirmation is available. If any evidence is stale, stop.
Otherwise request one UI confirmation and use expected-head merge. Do not infer
a grant from this template or historical text. After the action, verify merge
facts and stop; post-merge state requires its authorized adapter.
