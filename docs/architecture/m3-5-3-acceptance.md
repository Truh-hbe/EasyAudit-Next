# M3.5.3 — Finding & Action Collaboration Surface Acceptance Gate

Baseline:

```text
main@0d9d6e05bf18c9ec63acde87d39d0f7f8e03482e
```

This Acceptance belongs to `m3-5-3-finding-action-collaboration-surface.md` and is frozen before executable implementation begins.

The Gate PR itself is documentation-only. Before architecture approval, the diff must contain exactly the two M3.5.3 Gate documents and no executable source, migration, dependency, CI/workflow, or generated OpenAPI change.

## A. Scope and dependency acceptance

M3.5.3 passes only if implementation remains downstream of M2/M3 truth:

- Review Core lifecycle and Scenario authorization semantics are unchanged;
- the existing FindingParticipant participant-management invariant is strengthened with a final concurrency serialization guard before relationship persistence;
- no new Action approval/rejection workflow is introduced;
- no WorkItem/Todo or Product-owned assignment truth is created;
- no Notification/Management/Reminder Product Surface leaks into this slice;
- no new deadline/overdue rule is computed by React;
- no binary storage infrastructure is introduced;
- the exact Scenario UI registry remains the only Scenario-specific React extension boundary.

The FindingParticipant guard is accepted only as concurrency enforcement of already-existing Scenario semantics. It must not change who is authorized, which Finding lifecycles allow participant management, or which role/actor-kind combinations are valid.

Architecture/dependency tests must continue to prove backend modules do not import Product Surface code and generic React resource modules do not embed distributed Scenario identity branching.

## B. Gate diff acceptance

Before executable implementation is unlocked:

```text
changed files == 2
```

and the exact paths are:

```text
docs/architecture/m3-5-3-finding-action-collaboration-surface.md
docs/architecture/m3-5-3-acceptance.md
```

Forbidden before approval:

```text
web/**
src/easyaudit_next/**
alembic/**
package / lockfile
GitHub Actions / CI
OpenAPI generated artifacts
```

## C. Finding route authorization acceptance

Given a Finding route entered from any source, including a stale Workbench/Case link or browser history:

1. the current Finding GET is the authorization gate;
2. subordinate participant/action/submission/activity reads do not start before that gate succeeds;
3. if current access is refused or the resource is missing, protected cached Finding/child content is not rendered;
4. direct URL access cannot gain visibility merely because the user previously saw the parent Case;
5. switching user/session cannot reuse protected resource cache from the previous identity.

Tests must cover at least:

```text
authorized → Finding renders
same-org unrelated user → safe unavailable
cross-org actor → safe unavailable
previously authorized, then relationship revoked → stale route does not render old details
```

Where the backend returns 403 versus 404, the Product Surface may unify the visible unavailable state but must preserve safe cache behavior.

## D. Action route authorization acceptance

The same pattern applies to `/action-items/:actionItemId`:

- ActionItem GET is first;
- assignee/evidence/activity child reads require successful current Action visibility;
- stale parent Finding knowledge is not authority;
- unrelated/cross-org users receive no protected Action child content.

## E. Finding generic field fidelity

The Finding page renders generic data from the published wire resource without manufacturing competing facts.

Required checks:

- title, description, severity and lifecycle reflect the server response;
- raised timestamp uses the shared time-format boundary;
- `scenario_data` is not interpreted generically as workflow/authorization truth;
- no client-owned `due_at`, overdue flag, aggregate progress, owner cache, or lifecycle shadow is invented when absent from the wire resource.

## F. Exact Scenario UI acceptance

For a successful `process_review@1` Finding:

- exact adapter resolution succeeds;
- `issue_type` and `project_category` are rendered through the Scenario adapter;
- creation form submits those fields through `scenario_data`;
- backend remains final validator of non-blank/whitespace rules;
- no business default is silently inserted by React.

Counterexample tests are mandatory:

```text
process_review@99
→ generic Finding fields may render after authorization
→ Scenario-specific fields show unsupported/unavailable state
→ no v1 fallback
→ Scenario-specific creation/editing fails closed
```

Registry tests must continue proving duplicate registration rejection and exact `(key, version)` lookup.

## G. Finding creation acceptance

Finding creation is allowed only from an already-authorized ReviewCase context and only through the published create endpoint.

Tests must show:

- valid server success navigates/renders the returned persisted Finding;
- server 403 does not insert a local Finding into the Case list;
- server 409/422 does not leave a fake persisted row;
- Case lifecycle/Scenario validation remains server-owned;
- React does not pre-transition the parent Case or Finding.

## H. Participant display identity acceptance

Existing FindingParticipant remains the relationship truth.

If the implementation adds `actor_display_name` or equivalent:

- it is additive presentation data only;
- it is resolved only after current Finding authorization succeeds;
- it corresponds only to participant actors already returned for that Finding;
- no email, credential, platform role, unrelated department/user detail, or organization-wide listing is exposed accidentally;
- a stale display name cannot grant any mutation.

The UI must visibly distinguish user versus department relationships where needed without treating actor kind as permission proof.

## I. Participant candidate lookup acceptance

A participant assignment picker must not require raw UUID entry and must not become an ordinary-user directory.

Backend PostgreSQL/API tests must prove:

1. target Finding belongs to the current organization;
2. caller lacks participant-management permission → candidate search refused;
3. target is terminal/ineligible under current Scenario operation rules → candidate search refused or empty by the frozen implementation contract, never used to bypass mutation rules;
4. requested role/actor-kind invalid for exact Scenario → rejected;
5. Process Review `responsible_department + user` is rejected;
6. Process Review `owner/collaborator + department` is rejected;
7. valid role/kind search returns only bounded minimal identity results;
8. search text is required and bounded; result count is hard-limited;
9. no empty query can enumerate the whole organization;
10. candidate result does not bypass authoritative POST revalidation.

Frontend tests must show loading, no-results, error and selection states without caching the candidate list as authority.

## J. Participant mutation acceptance

Adding a participant uses the existing Finding command, strengthened so the existing terminal-Finding invariant remains true under PostgreSQL concurrency.

Mandatory behavior:

- mutation success refreshes participant state;
- 403 preserves current server relationship list and shows refusal;
- 409/422 does not locally add the actor;
- duplicate/invalid relationship errors remain authoritative;
- no local removal/edit behavior exists without a backend command;
- an early authorization/lifecycle snapshot is insufficient to persist a FindingParticipant relationship fact;
- immediately before relationship persistence, the backend serializes against concurrent terminal Finding transition, refreshes the persisted Finding state, and re-checks current exact-Scenario participant-management operation state;
- if a competing terminal transition committed first, participant creation aborts as a stale/concurrency conflict and maps to `409 Conflict`;
- an aborted stale participant mutation persists no FindingParticipant, no `finding.participant_added` Activity, and no related Notification delivery fact.

The Gate does not require one repository method name. PostgreSQL `SELECT ... FOR UPDATE` plus refreshed ORM state is acceptable, as is an equivalent serialization mechanism, provided the same invariant is proven.

A real PostgreSQL concurrency counterexample is mandatory:

```text
Tx A
add participant
→ initial Finding/context read is non-terminal
→ authorization / preliminary validation passes
→ pause before final persisted Finding guard

Tx B
VERIFYING → CLOSED
or
OPEN → VOIDED
→ commit before Tx A obtains/completes its final guard

Tx A
→ final guard observes refreshed terminal Finding
→ participant-management operation rejected
→ FindingParticipant NOT inserted
→ finding.participant_added Activity NOT inserted
→ related Notification NOT created
→ stale/concurrency response = 409
```

The test must prove database state after both transactions, not only an exception mapper. It must fail if the implementation merely repeats an unlocked read or trusts the pre-final snapshot.

At least one frontend test must deliberately render an assignment affordance for a user who later loses authority or whose Finding becomes ineligible, return authoritative refusal/conflict, and prove the UI does not persist the local participant.

## K. Action list/detail acceptance

Finding Action list and Action detail reflect the existing wire model only:

```text
id
finding_id
title
lifecycle
due_at
completed_at
```

No Action-level approval/rejection/verification state may appear.

Tests must cover `todo`, `in_progress`, `done`, `cancelled` presentation and due-time formatting without converting due time into a competing overdue rule.

## L. Action creation acceptance

Action creation uses the existing Finding-scoped command.

Tests must prove:

- authorized valid creation uses returned ActionItem truth;
- unauthorized/stale Finding owner presentation cannot force creation;
- invalid Finding lifecycle or server validation refusal leaves no local persisted Action;
- successful creation refreshes the parent Action list;
- no client-created ID/lifecycle becomes canonical before success.

## M. Assignee display and candidate acceptance

Assignee display identity follows the same target-scoped additive rule as Finding participants.

Assignee candidate search must:

- require current Action target authorization and relationship-management authority;
- validate exact Scenario role/actor-kind contract;
- remain bounded/minimal;
- refuse ordinary org enumeration;
- not grant mutation authority.

Process Review acceptance must prove Action `primary` and `collaborator` candidate actors are Users, not Departments.

## N. Assignee mutation acceptance

Adding an assignee uses the existing command and current Scenario operation rules.

Tests must include:

- valid owner-managed assignment;
- unauthorized actor refusal;
- terminal/ineligible Action refusal;
- duplicate/invalid assignment refusal;
- successful refresh;
- no local delete/replace UI when no backend command exists.

## O. Action transition acceptance

The Product Surface may invoke only existing Action commands supported by the backend contract, including current Process Review actions:

```text
start
complete
cancel
reopen
```

For every command:

- server mutation response is authoritative;
- 409 stale/concurrent conflict is surfaced;
- affected Action and parent list are refetched after conflict/success as appropriate;
- required reason validation remains backend-owned;
- no blind semantic retry occurs.

A concurrency counterexample is mandatory:

```text
render Action at T0
another actor transitions it
user submits stale command at T1
backend 409
→ no success toast/state
→ current Action refetched
→ server lifecycle wins
```

## P. Rectification plan Submission acceptance

For `process_review@1`, the plan Submission UI may collect the exact currently defined plan payload such as `root_cause` through the exact Scenario adapter.

Tests must prove:

- blank/invalid payload receives authoritative 422 and no local Submission is inserted;
- successful POST renders/refetches the persisted Submission;
- Finding remains whatever lifecycle the server returns;
- React does not derive lifecycle from Submission stage/payload.

## Q. Completion Submission acceptance

For completion / submit-for-verification:

- UI calls the existing formal rectification Submission endpoint;
- backend verifies non-cancelled Action existence/completion and payload requirements;
- failed precondition does not locally move Finding to verifying;
- successful response updates/refetches Finding and Submission history;
- concurrent stale Finding state follows 409 behavior.

A required counterexample:

```text
UI sees all Actions done
one Action is reopened before submit
completion POST rejected by server
→ Finding stays/refetches authoritative state
→ no local VERIFYING transition
```

## R. Verification approve/reject acceptance

Approve/reject uses the existing verification-Submission endpoint, never a Product-owned lifecycle edit.

Tests must cover:

- authorized reviewer approve success;
- authorized reviewer reject success with required payload/reason semantics;
- unauthorized user 403;
- stale lifecycle 409 where applicable;
- validation 422;
- after success, Finding and Submission history are refreshed;
- UI role strings are not treated as proof of permission.

At least one test must intentionally have a client presentation that appears actionable but server authority has changed; refusal must win without local state mutation.

## S. Reopen acceptance

Reopen uses the published reopen endpoint.

Tests must prove:

- required reason remains server-owned validation;
- authorized success uses returned Finding lifecycle;
- unauthorized/stale/invalid request preserves server truth;
- no client-side direct `closed → rectifying` mutation exists.

## T. Finding-scoped Submission history acceptance

If the new read prerequisite is implemented as `GET /findings/{id}/submissions` (or equivalent), PostgreSQL/API tests must prove:

- current Finding visibility is required;
- only rows with the requested `finding_id` are returned;
- sibling Finding and Case-only Submissions do not leak;
- rectification and verification Submissions both appear when persisted;
- stable order is `submitted_at ASC, id ASC`;
- GET is side-effect free;
- no history row is copied/rewritten into a Product table.

Frontend tests must prove generic history rendering does not infer current lifecycle or current authorization from old payloads. Exact Scenario payload rendering must fail closed on unknown Scenario UI versions.

## U. Evidence acceptance

M3.5.3 only renders existing Action Evidence metadata.

Acceptance requires:

- Evidence list begins only after current Action authorization;
- metadata is associated with the requested Action only;
- no raw `storage_key`/SHA entry form is presented to ordinary users as file upload;
- no binary upload/download, object storage, signed URL, antivirus/scanning, or cleanup semantics are added in this slice;
- Evidence metadata does not become a Submission copy.

The existing backend registration endpoint may remain untouched and unexposed by Product UI.

## V. Finding Activity acceptance

The narrow Finding Activity read must prove:

- current Finding visibility required first;
- only exact Finding-subject Activity returned;
- ActionItem/Submission/sibling Finding Activity excluded;
- stable order follows established Activity ordering convention;
- first Product DTO excludes generic metadata JSON;
- GET creates no Activity/Notification/other side effect;
- append-only protection remains unchanged.

Frontend Activity UI must display historical facts, not infer current permissions/lifecycle from them.

## W. ActionItem Activity acceptance

The same tests apply to ActionItem subject isolation:

- exact current Action authorization;
- only exact ActionItem-subject Activity;
- no parent Finding/sibling/Submission rows;
- no metadata leakage;
- side-effect free and stable ordering.

## X. Error/stale-data acceptance

Shared Product API behavior must distinguish and safely handle:

```text
401 → session-expiry/auth flow
403 → current business refusal
404 → unavailable/missing
409 → stale/concurrent/state conflict
422 → validation/business input failure
```

A FindingParticipant request whose earlier non-terminal snapshot becomes stale before the final relationship write is specifically a `409`, not a successful write and not a client-authoritative 422 reinterpretation.

M3.5.3 must not add one-off raw `fetch()` error handling that bypasses the shared Product API boundary.

After 409/refusal that indicates stale business state, affected server data is refetched before further semantic action. Blind automatic mutation retry is forbidden.

## Y. Cache and refresh acceptance

Successful mutations invalidate/refetch all visible affected projections without maintaining a shadow lifecycle.

Minimum matrix:

```text
Finding create         → Case Findings list + new Finding
participant add        → participant list
Action create          → Action list + new Action
assignee add           → assignee list
Action transition      → Action detail + parent Action list
rectification submit   → Finding + Submission history + relevant Actions
verification submit    → Finding + Submission history + Activity as rendered
reopen                 → Finding + Activity as rendered
```

A stale/conflicted participant add also refetches the current Finding and participant list before another semantic mutation is attempted.

Logout/session identity change continues to clear protected Product caches per M3.5.1.

## Z. No M3.5.4 leakage acceptance

Static/component/browser tests must prove M3.5.3 does not require Product usage of:

```text
/me/notifications
management collection/progress UI
manual nudge endpoints
recipient selection
reminder cadence/scheduler controls
```

Existing backend Notification side effects caused by authoritative commands are allowed and must continue to regress successfully; they do not unlock Notification Center UI.

## AA. Frontend structure acceptance

The executable slice should add bounded feature ownership such as:

```text
web/src/features/findings/
web/src/features/actions/
```

with Scenario-specific Finding presentation/forms remaining in `web/src/scenarios/` and HTTP access through the existing shared API boundary.

Acceptance fails if:

- `App.tsx` becomes the business workflow implementation;
- generic Finding/Action components contain `process_review` identity branching;
- feature components scatter independent raw fetch clients;
- TypeScript DTOs become a second lifecycle/permission model.

## AB. Required regression / CI evidence

Final executable head must pass the repository's normal exact-head CI, including at minimum:

```text
Ruff
mypy
architecture checks
OpenAPI checks
Alembic migration path
PostgreSQL pytest regression
web typecheck/lint/build/test pipeline established by M3.5.1/2
```

M3.5.3 adds focused backend PostgreSQL tests for any read prerequisites and for the FindingParticipant final serialization counterexample, plus focused React tests for Finding/Action behavior.

The FindingParticipant concurrency proof must exercise real PostgreSQL transaction interleaving and assert the final persisted relationship, Activity, and Notification facts; an in-memory/mock-only test is insufficient.

Final Review must verify the exact candidate head, not an earlier successful run.

## AC. Final acceptance statement

M3.5.3 is complete only when:

> an authorized user can enter an original Finding/Action resource, understand its current relationships/history, and invoke the existing rectification/verification commands while every authorization, lifecycle, Submission, assignment, concurrency, and provenance decision remains backend-authoritative.

If implementation requires React to become the canonical answer to “may this user do this business action?”, the Gate has failed and implementation must stop for architecture review.