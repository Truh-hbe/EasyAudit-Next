# M3.5.3 — Finding & Action Collaboration Surface Gate

M3.5.3 begins only after M3.5.2 is merged and frozen.

Baseline:

```text
main@0d9d6e05bf18c9ec63acde87d39d0f7f8e03482e
```

Fixed upstream references:

```text
M3.5 Product Surface Architecture Gate:
d19c897468fe1c179c939a59b8fd38f69c7c87c1

M3.5.2 Final Review fixed head:
4890e1a83f37c0d8463b0bddf32a74117f0aca02

M3.5.2 merge/current baseline:
0d9d6e05bf18c9ec63acde87d39d0f7f8e03482e
```

This Gate is design-only. Before Gate approval it must not add React implementation, backend executable code, migrations, package/lockfile changes, CI changes, or Review Core / Scenario workflow semantics.

## Goal

Replace the M3.5.2 honest placeholders for:

```text
/findings/:findingId
/action-items/:actionItemId
```

with the first real collaboration surface over existing M2 facts and commands:

```text
ReviewCase
  ↓
Finding
  ├── generic facts + exact Scenario data
  ├── participants
  ├── ActionItems
  ├── formal Submissions
  └── Finding-subject Activity
       ↓
ActionItem
  ├── generic facts / due time / lifecycle
  ├── assignees
  ├── Evidence metadata
  └── ActionItem-subject Activity
```

Invariant:

> React composes existing backend facts and commands. It is never a source of authorization, workflow legality, lifecycle, assignment authority, deadline truth, Submission meaning, or Activity provenance.

## Frozen scope

M3.5.3 includes:

- Finding detail and creation from an already-authorized ReviewCase context;
- Finding participant assignment through the existing command;
- ActionItem list/detail, creation, assignee assignment and transitions;
- rectification plan/completion Submission UX;
- Finding verification approve/reject and reopen UX;
- one coherent Finding-scoped Submission-history read projection;
- read-only existing Evidence metadata;
- exact-version Finding Scenario UI extension;
- narrow, target-scoped assignment-candidate lookup;
- target-scoped participant/assignee display-name enrichment;
- narrow Finding-subject and ActionItem-subject Activity reads;
- authoritative 403/404/409/422 handling and stale-state refresh.

Out of scope:

- new Finding/Action lifecycle states or Review Core permissions;
- changes to Scenario workflow/authorization semantics or a new `allowed_actions` Scenario contract;
- general Finding PATCH/edit semantics;
- participant/assignee removal where no backend command exists;
- Action-level approve/reject/pending-review lifecycle;
- binary file upload/download, StorageBackend, S3/MinIO, signed URLs, file scanning;
- exposing `storage_key` / `sha256` as ordinary user upload inputs;
- Notification, Management, Reminder Product UI;
- new overdue/deadline rules, WorkItem/Todo truth, migrations;
- an organization-wide directory for ordinary users.

M3.5.4 remains Notification + Management + Reminder Product Surface. M3.5.5 remains final acceptance/responsive/polish.

## Existing backend commands remain authoritative

M3.5.3 consumes the published M2 endpoints for Finding, Action, participants, assignees, rectification Submissions, Evidence registration/listing, verification and reopen. It does not introduce Product-only replacement mutations.

Existing business endpoint semantics remain authoritative:

```text
401 authentication/session failure
403 business authorization refusal
404 missing/non-resolved resource
409 concurrency/state/integrity conflict
422 request or Scenario/business validation failure
```

The UI may present 403 and 404 through one safe unavailable experience, but it must not rewrite backend semantics or render protected cached data.

## Resource-first route safety

For `/findings/:findingId` the first protected business read is the current Finding GET. Child reads begin only after it succeeds. On refusal/missing, stale participants/actions/submissions/activity must not render.

For `/action-items/:actionItemId` the first protected business read is the current ActionItem GET. Assignee/evidence/activity reads begin only after success.

Workbench rows, ReviewCase links, browser history and later Notification pointers are navigation hints, never capability tokens.

## Finding surface

Recommended structure:

```text
Header
├── title / severity / lifecycle
├── parent ReviewCase navigation
└── raised time / presentation-safe actor identity

Overview
├── description
└── exact Scenario section

Collaboration
├── participants
├── ActionItems
├── Submissions
└── Finding Activity
```

Generic fields stay direct wire facts. M3.5.3 does not invent a Finding deadline/overdue fact when the published Finding resource does not contain one.

Finding creation uses the existing ReviewCase-scoped create endpoint and only its published fields: title, description, severity, and exact-Scenario `scenario_data`. The successful server response becomes authoritative; React does not fabricate a persisted Finding before backend validation succeeds.

## Exact-version Finding Scenario UI

M3.5.2 established the executable exact-version Scenario UI registry. M3.5.3 extends that same registry, conceptually:

```text
process_review@1
├── CaseScenarioSection
└── FindingScenarioSection / Finding creation fields
```

Resolution remains exact by `(scenario_key, scenario_version)`. Unknown versions fail closed for Scenario-specific display/editing; no latest/key-only fallback is permitted.

For `process_review@1`, the current backend Finding data contract requires non-blank:

```text
issue_type
project_category
```

The adapter may label/render/collect those fields but cannot redefine validation or silently supply business defaults. Generic Finding/Action components must not contain distributed `process_review` branching.

## UI affordance is not authorization

The current M2 Scenario contract does not publish typed `allowed_actions`. M3.5.3 does not change that contract merely for button visibility.

React may use returned lifecycle and exact Scenario presentation to avoid obviously irrelevant controls, but it must not derive permission from `role_key`, assignee role, or platform role. A rendered control can still receive authoritative 403/409/422 and must refresh server truth.

Forbidden authority patterns include treating `reviewer + verifying`, `owner`, or `primary assignee` as client-side proof that a command is permitted.

## Human-readable participant / assignee identity

Baseline participant and assignee DTOs expose actor UUID/kind/role but no human-readable name. Ordinary users must not use system-admin APIs as a directory.

M3.5.3 may add an additive target-scoped presentation field such as:

```text
actor_display_name
```

only after current target authorization succeeds and only for actors already exposed by that authorized relationship response. The underlying FindingParticipant / ActionAssignee remains the relationship truth.

## Assignment candidate lookup

A usable assignment form cannot require raw UUID input, but this slice must not create a general org directory.

M3.5.3 therefore permits narrow target- and role-scoped candidate search for participant/assignee management. Exact route spelling may vary; its invariants are fixed:

1. resolve the target inside the current organization;
2. require the same current business authorization and operation-state boundary used to manage that relationship;
3. validate requested role + actor kind against the exact historical Scenario role specification;
4. return bounded search results only, not an org dump;
5. expose presentation-minimal identity only (`actor_kind`, `actor_id`, `display_name`);
6. candidate presence never guarantees a later mutation succeeds;
7. the mutation revalidates all current permissions/state;
8. `system_admin` gains no business bypass.

First implementation should require non-blank search text (recommended minimum 2 characters) and a hard result limit (recommended max 20).

For Process Review v1 this must preserve the existing actor-kind contract: `responsible_department` is Department-only; Finding `owner/collaborator` and Action `primary/collaborator` are direct User actors.

## ActionItem surface

ActionItem remains a rectification action, not a second Finding. It answers:

```text
what must be done?
what is its lifecycle?
who is assigned?
when is it due / completed?
what Evidence metadata exists?
what ActionItem-subject Activity occurred?
```

Existing Process Review actions remain `start`, `complete`, `cancel`, `reopen`. M3.5.3 adds no Action-level approval/rejection/verification lifecycle. Formal approve/reject remains Finding verification.

No assignee removal/replacement behavior may be simulated locally if no published backend command exists.

## Formal Submission UX

Rectification continues through the existing Finding rectification-Submission endpoint. For `process_review@1`, existing policy distinguishes plan submission and completion submission, with backend-owned payload validation and lifecycle effects. Exact Scenario UI may provide the current form fields (including plan `root_cause` and completion `comment`) but backend 422 remains final.

Verification approve/reject continues through the existing verification-Submission endpoint. Reopen continues through the existing reopen endpoint. M3.5.3 must not replace these with direct lifecycle edits.

After success, returned Submission/Finding facts are accepted and affected resource queries are refreshed. React must not independently move a Finding to `verifying`, `closed`, or `rectifying`.

## Finding-scoped Submission history prerequisite

The baseline exposes rectification Submission listing but not an equivalent complete verification-history read. M3.5.3 may add one narrow read-only projection, conceptually:

```http
GET /api/v1/findings/{finding_id}/submissions
```

Semantics:

```text
current Finding visibility authorization
→ only persisted Submissions whose finding_id is the requested Finding
→ stable order: submitted_at ASC, id ASC
```

It does not create/copy a second Submission aggregate and must not expose unrelated Case-only or sibling-Finding submissions. Generic UI must not infer current lifecycle/authority from historical payload JSON; Scenario-specific payload interpretation belongs behind the exact Scenario UI adapter.

## Evidence boundary

The current Evidence registration wire contract accepts storage metadata, but the repository baseline does not provide browser binary upload/storage transport. Therefore this slice renders existing Action Evidence metadata read-only and does not expose the raw registration DTO as an ordinary file-upload form.

Users must not be asked to type `storage_key` or SHA-256. Binary upload/download and storage security require a separate architecture decision.

## Finding / Action Activity reads

Following M3.5.2's narrow Case-subject pattern, this slice may add:

```text
Finding activity read
→ current Finding authorization
→ only Activity whose subject is exactly that Finding

ActionItem activity read
→ current ActionItem authorization
→ only Activity whose subject is exactly that ActionItem
```

The first Product Activity DTO remains presentation-safe and metadata-free:

```text
id
subject_type
subject_id
event_type
actor_id
occurred_at
```

Finding Activity must not aggregate child Action/Submission Activity. Action Activity must not leak parent/sibling/Submission Activity. Reads are side-effect free and preserve append-only history.

## Stale/conflict behavior

Expected flow:

```text
render T0
→ another actor changes server truth
→ command at T1
→ authoritative refusal/conflict
→ surface message
→ refetch affected current resource/projections
→ no blind semantic retry
```

A 409 is never converted to success because local lifecycle looked valid. A 422 never causes client-side lifecycle mutation.

Successful Action mutations refresh Action detail and relevant parent Action list. Relationship changes refresh relationship views. Rectification/verification/reopen refresh Finding plus affected Submission/Action/Activity projections. No long-lived shadow lifecycle is allowed.

## Frontend ownership

Expected conceptual ownership:

```text
web/src/features/findings/
web/src/features/actions/
web/src/scenarios/
web/src/api/
```

Generic feature modules own resource composition and command UX. Exact Scenario fields/forms stay behind the central Scenario registry. Shared API transport remains the only HTTP boundary; feature components do not scatter raw fetch calls or duplicate wire DTOs.

## Gate discipline

Executable implementation remains locked until this Gate and `m3-5-3-acceptance.md` pass review.

Before approval the Draft PR must contain exactly:

```text
docs/architecture/m3-5-3-finding-action-collaboration-surface.md
docs/architecture/m3-5-3-acceptance.md
```

No `web/**`, `src/easyaudit_next/**`, migration, package/lockfile, CI/workflow, or generated OpenAPI artifact may appear in the Gate diff.

After Gate approval implementation may proceed on the same Draft PR within the frozen boundary. Final Review then fixes one exact executable head and requires full normal CI plus M3.5.3 Acceptance evidence.

## Final invariant

M3.5.3 succeeds when an authorized user can move from ReviewCase into original Finding/Action resources, perform existing collaboration commands, and understand current relationships/history without any React module becoming a parallel policy engine.