---
description: Create only the next authorized EasyAudit Gate Draft
argument-hint: "<slice>"
---
Prepare only the Gate Draft for `$1`. First run EasyAudit preflight and verify
machine predecessors. Use the exact state Scope; do not implement executable
work, review, authorize, merge, deploy or access secrets. Return branch, base,
commit, changed paths, Gate result and Draft PR URL, then stop.
