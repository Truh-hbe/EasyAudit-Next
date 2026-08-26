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
- M2.3 Finding action-summary fields now read real persisted Action state, excluding `cancelled`;
- a completion Submission is rejected with zero non-cancelled Actions;
- a completion Submission is rejected while any non-cancelled Action is unfinished;
- completion may advance a Finding to `verifying` only after every non-cancelled Action is `done`;
- Action lifecycle changes use PostgreSQL compare-and-swap;
- two concurrent Action transitions from the same old lifecycle yield one success, one conflict,
  and one transition Activity;
- Evidence has organization-safe ActionItem/uploader foreign keys and immutable identifying
  metadata including SHA-256;
- Evidence UPDATE and DELETE are rejected at the PostgreSQL layer;
- formal Submission UPDATE and DELETE are rejected at the PostgreSQL layer;
- rectification plan Submission does not change the Finding lifecycle;
- completion Submission, Finding CAS, and Submission-target Activity share one request transaction;
- two concurrent completion Submissions yield one success, one CAS conflict, one persisted
  completion Submission, and one `finding.submitted_for_verification` Activity;
- a persistence failure after the Finding CAS rolls the whole transaction back to `rectifying`
  without a partial Submission;
- Scenario/business validation failures return 422 while CAS and persistence conflicts remain 409;
- verification approve/reject, Finding reopen, and ReviewCase closure remain outside M2.4; and
- all prior M1, M2.2, and M2.3 regression and atomicity tests remain green.

The PR remains Draft and unmerged after this gate. M2.5 does not begin until Final Architecture
Review explicitly releases M2.4.

The M2.5 closure gate remains separately recorded: PostgreSQL concurrency coverage must prove that
ReviewCase closure racing with a final Finding transition cannot persist a `closed` Case containing
a non-terminal Finding.
