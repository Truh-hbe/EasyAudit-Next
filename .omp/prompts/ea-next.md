---
description: Generate only the next legal EasyAudit action prompt from machine state
---
Call `ea_next` and return its generated prompt. Do not edit state, send the
prompt to another system, start implementation, authorize, merge or deploy.
If a predecessor or evidence requirement is blocked, return STOP and explain
the exact machine evidence that is missing.
