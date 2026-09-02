---
description: Reverify the state-bound EasyAudit PR before a one-shot merge and rebaseline action
---
Call `ea_authorized_merge` without model-supplied PR or SHA. Do not accept historical or model-created authorization. The tool must derive
PR, fixed candidate and expected control head from protected state and verified
remote evidence; require MERGE_AUTHORIZED, structured Review PASS, trusted
required checks and current human confirmation. If any evidence is stale, stop.
After a remote-only merge failure, report `REMOTE_MERGED_REBASELINE_PENDING`
and require the separately confirmed recovery tool.
