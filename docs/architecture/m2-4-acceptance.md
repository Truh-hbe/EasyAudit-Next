# M2.4 Acceptance Gate

M2.4 is ready for Final Architecture Review only when CI proves:

- Alembic upgrades the complete PostgreSQL chain through `20260826_0008`;
- Review Core remains free of concrete Scenario imports and Process Review branching;
- `ScenarioPolicy` formally requires Scenario-owned `action_operations`;
- ActionItem create/list/get are organization-scoped and Scenario-authorized;
- Action lifecycle cannot be supplied on create or changed by an ordinary PATCH;
- ActionAssignee actor/role combinations follow the exact ScenarioVersion RoleSpecification;
- ActionAssignee targets are active and organization-local;
- Process Review allows rectification only while the parent Case is `in_progress` or
  `awaiting_closure` and the Finding is `rectifying`;
- Process Review freezes ordinary assignee management after an Action becomes `done` or
  `cancelled`;
- Department responsibility grants visibility but not Action write authority;
- direct Action `primary`/`collaborator` relationships can contribute Finding/Case visibility and
  assigned-Action authority without expanding the base M2.3 repository contract;
- Review Core supplies Scenario-neutral Action operation facts rather than Scenario-specific
  branches;
- `RectificationRepository`, not the base `ReviewCoreRepository`, owns the Finding-level
  rectification concurrency guard;
- the PostgreSQL guard uses the organization-scoped parent Finding row with `FOR UPDATE`;
- the M2.4 write lock order is consistently `Finding -> Action/Assignee/Evidence/Submission`;
- Action and Finding state reread after waiting on the guard cannot reuse stale SQLAlchemy identity
  map values; decisive post-lock reads are refreshed from PostgreSQL;
- Action create, ActionAssignee mutation, Action transition, Evidence registration, rectification
  plan Submission, and completion Submission all use the same parent Finding guard before decisive
  mutable facts are consumed;
- M2.3 Finding action-summary fields now read real persisted Action state, excluding `cancelled`;
- a completion Submission is rejected with zero non-cancelled Actions;
- a completion Submission is rejected while any non-cancelled Action is unfinished;
- completion may advance a Finding to `verifying` only after every non-cancelled Action is `done`;
- an unrelated same-organization user is denied `view_finding` before completion Action-state or
  lifecycle validation can expose business facts;
- Action lifecycle changes retain PostgreSQL compare-and-swap;
- two concurrent Action transitions from the same old lifecycle yield one success, one Action CAS
  conflict, and one transition Activity even with the parent Finding guard present;
- Evidence has organization-safe ActionItem/uploader foreign keys and immutable identifying
  metadata including SHA-256;
- Evidence UPDATE and DELETE are rejected at the PostgreSQL layer;
- formal Submission UPDATE and DELETE are rejected at the PostgreSQL layer;
- rectification plan Submission does not change the Finding lifecycle;
- completion Submission, Finding CAS, Submission, and Submission-target Activity share one request
  transaction;
- two concurrent completion Submissions still yield one success, one Finding concurrency conflict,
  one persisted completion Submission, and one `finding.submitted_for_verification` Activity;
- completion racing a `done -> reopen` Action transition can never persist
  `Finding=verifying + Action=in_progress`: either completion wins the Finding guard and reopen is
  rejected as concurrent, or reopen wins and completion rereads the unfinished Action and is
  rejected;
- completion racing Action creation can never persist `Finding=verifying` together with a newly
  created `todo` Action: either completion wins and creation is rejected as concurrent, or creation
  wins and completion rereads the new unfinished Action and is rejected;
- a persistence failure after the Finding CAS rolls the whole transaction back to `rectifying`
  without a partial Submission;
- Scenario/business validation failures return 422 while Action/Finding concurrency and persistence
  conflicts remain 409;
- verification approve/reject, Finding reopen, and ReviewCase closure remain outside M2.4; and
- all prior M1, M2.2, and M2.3 regression and atomicity tests remain green.

The PR remains Draft and unmerged after this gate. M2.5 does not begin until Final Architecture
Review explicitly releases M2.4.

The M2.5 closure gate remains separately recorded: PostgreSQL concurrency coverage must prove that
ReviewCase closure racing with a final Finding transition cannot persist a `closed` Case containing
a non-terminal Finding.
