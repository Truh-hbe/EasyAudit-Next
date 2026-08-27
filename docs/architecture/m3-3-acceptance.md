# M3.3 Acceptance Gate

M3.3 is ready for Final Architecture Review only when CI proves all of the following.

This Gate applies to **Management Progress & Overdue Queries** only. The PR must remain Draft and unmerged until implementation and all Acceptance evidence are complete.

## Architecture boundary

- M3.3 is read side only.
- No `ManagementCase`, `SupervisionTask`, `ProgressSnapshot`, `OverdueRecord`, `AttentionItem`, second responsibility table, or equivalent business persistence exists.
- Review Core lifecycle values, transition semantics, Scenario contracts unrelated to management query authorization, concurrency guards, and lock order remain unchanged.
- `ReviewCoreRepository` is not expanded with management-only query methods.
- Review Core does not import the M3.3 management module.
- Notification does not become a source of current management scope or overdue truth.
- No reminder/nudge/scheduler behavior enters M3.3.
- No generic `Finding.due_at` is added merely for dashboard convenience.
- No generic business `manager`/`supervisor` platform role is introduced.

## API contract

The first management query surface provides the equivalent of:

```http
GET /api/v1/management/review-cases
GET /api/v1/management/review-cases/{case_id}/progress
```

CI must prove:

- both endpoints require the existing BusinessIdentity dependency;
- both endpoints are GET/read-only;
- OpenAPI documents request filters and response DTOs;
- the collection endpoint uses bounded pagination;
- the progress endpoint is organization + authorization scoped before response materialization;
- neither endpoint writes Review Core state, Notification state, or Activity; and
- unauthenticated requests are rejected.

## Management scope

For every returned ReviewCase, CI must prove all of the following:

1. the caller is active in the same Organization;
2. the caller has a direct CaseMember relationship on the candidate Case;
3. the exact historical Scenario Policy allows `manage_case_members` for the target Case context; and
4. the exact historical Scenario Policy allows `view_case` for the target Case context.

CI must include negative controls proving that:

- an unrelated same-Organization user cannot see the Case;
- a CaseMember whose role permits ordinary viewing but not `manage_case_members` does not enter the management collection;
- `system_admin` without business Case authority receives no implicit management visibility;
- a known Case UUID does not bypass scope; and
- a Case in another Organization is not disclosed.

The implementation must not test `role_key == "lead"` or any other Process Review-specific management shortcut.

## Exact ScenarioVersion

CI must prove management authorization uses the ReviewCase's persisted exact `(scenario_key, scenario_version)`.

At minimum, use a custom/test Scenario or multiple versions capable of exposing an error if the implementation:

- resolves the latest Scenario version instead of the persisted one;
- resolves by Scenario key only; or
- hard-codes Process Review role names.

A Case created under version A must continue to use version A's management authorization after version B is registered.

## Target-scoped authorization facts

Bulk loading must not broaden authorization context.

CI must prove:

- Case management authorization uses only facts belonging to that Case;
- Finding visibility uses the parent Case grants, only the target Finding grants, and only Action grants under that Finding;
- sibling Finding grants do not authorize or reveal another Finding;
- sibling Action grants do not authorize or reveal another Finding/Action aggregate; and
- bulk SQL fetches are grouped by exact target before `ScenarioPolicy.authorization.allows(...)` is evaluated.

A custom Scenario must be able to fail the test if grants are merged too broadly.

## Child privacy and aggregate leakage

Management totals must never leak hidden child resources.

CI must include one managed Case containing at least:

```text
Finding A: caller may view
Finding B: caller may not view
```

and prove that the management response:

- includes Finding A in permitted counts/detail;
- excludes Finding B identifiers and detail;
- does not increment total Finding counts because of B;
- does not increment Action counts because of Actions under B;
- does not increment overdue counts because of Actions under B; and
- does not expose severity counts or any other aggregate derived from B.

## Factual progress projection

The management response may expose factual lifecycle counts, but no invented percent-complete business truth.

CI must prove correct aggregation of persisted Finding lifecycle values:

```text
open
rectifying
verifying
closed
voided
```

and persisted Action lifecycle values:

```text
todo
in_progress
done
cancelled
```

where those rows are authorized for disclosure.

If severity counts are exposed, they must exactly reflect authorized persisted Finding severities.

No persisted `progress_status` or percentage field may be introduced unless separately reviewed.

## Deadline projection

At one captured timezone-aware `as_of` value:

```text
ReviewCase overdue
= planned_end_at < as_of
  AND lifecycle in {scheduled, in_progress}

ActionItem overdue
= due_at < as_of
  AND lifecycle in {todo, in_progress}

Due soon
= as_of <= deadline <= as_of + 7 days
  AND the same eligible lifecycle rules
```

CI must prove:

- overdue Case inclusion;
- draft/awaiting_closure/closed/cancelled Case exclusion from Case overdue status;
- overdue todo/in_progress Action inclusion;
- done/cancelled Action exclusion;
- exact `deadline == as_of` behavior;
- exact `deadline == as_of + 7 days` behavior if due-soon is exposed;
- null deadlines are excluded from deadline buckets; and
- all deadline calculations in one response use the same captured `as_of`.

## No synthesized Finding deadline

CI or architecture checks must prove no Finding deadline is derived from:

- `scenario_data`;
- ReviewCase `planned_end_at`;
- minimum/maximum Action `due_at`;
- Submission timestamps; or
- any other heuristic.

M3.3 must not add a Finding deadline column or schema migration for one.

## Collection filters and ordering

If the collection supports `review_plan_id`, `lifecycle`, or `deadline_status`, CI must prove filters are applied only inside the caller's already-authorized management scope.

No filter may broaden visibility.

Deterministic ordering must be proven. For the initial risk-oriented order this means equivalent behavior to:

1. overdue Cases first;
2. nearest non-overdue `planned_end_at` next;
3. null deadlines later; and
4. stable Case UUID tie-break.

Repeated requests against unchanged data must return the same order.

## Progress detail

For an authorized managed Case, the detail endpoint must return one coherent `as_of` snapshot containing only authorized facts.

CI must prove:

- Finding detail rows are target-authorized;
- per-Finding Action aggregates correspond only to Actions under that Finding;
- overdue/due-soon Action items, if exposed, are deterministically ordered;
- the endpoint does not become an alternate write API; and
- a known foreign or unauthorized Case UUID returns the same non-disclosing not-found behavior used elsewhere in the business API.

## Query performance foundation

PostgreSQL integration tests must prove the dashboard does not use one query loop per Case/Finding/Action.

At minimum:

- candidate Case membership discovery is bulk;
- Scenario metadata loading is category-bounded;
- relationship facts used for authorization are bulk-loaded and grouped by target;
- Finding lifecycle aggregation is bulk/category-bounded;
- Action lifecycle/deadline aggregation is bulk/category-bounded; and
- increasing managed Case count materially, for example from 5 to 50/100, does not produce proportional SQL statement growth.

The test must not freeze one exact SQL count as a permanent contract, but it may enforce a small implementation-level upper bound to catch N+1 regressions.

PostgreSQL query plans or executed query patterns must justify any new indexes.

No denormalized management table/materialized business snapshot may be introduced as a shortcut.

## Organization isolation

PostgreSQL/API tests must use at least two Organizations and prove:

- Case candidates are organization-scoped before materialization;
- child Finding/Action aggregates cannot cross Organization boundaries;
- a foreign ReviewPlan filter cannot reveal another Organization's Cases;
- foreign UUIDs do not disclose resource existence; and
- platform administrator status does not override business scope.

## No Activity / Notification side effects

Before and after both M3.3 GET endpoints, CI must prove:

- Review Core entity state is unchanged;
- Activity count is unchanged;
- Notification count/read state is unchanged; and
- no request transaction creates durable business rows.

## No M3.4 leakage

The M3.3 PR must not contain:

- manual remind/nudge endpoints;
- new deadline-reminder Notification kinds;
- scheduler or cron code;
- periodic overdue scans;
- reminder cadence;
- escalation;
- snooze;
- user notification preferences; or
- external email/webhook/IM/push delivery.

## Regression gate

- All M1/M2/M3.1/M3.2 tests remain green.
- Existing Process Review E2E remains unchanged in meaning.
- Existing PostgreSQL concurrency tests remain green.
- M3.2 exact Activity provenance and Notification idempotency tests remain green.
- Ruff passes.
- mypy passes.
- architecture checks pass.
- OpenAPI contract checks pass.
- Alembic migration chain remains green.

## M3.3 end-to-end proof

A PostgreSQL integration/API test must create at least two Organizations and multiple same-Organization users, then prove one management user's view across a shape equivalent to:

```text
Case A: caller can manage_case_members and view_case
  Finding A1: visible, rectifying
    Action A1-1: in_progress and overdue
    Action A1-2: done
  Finding A2: visible, verifying

Case B: caller is CaseMember but cannot manage_case_members
Case C: caller can ordinary-view only
Case D: managed Case with a hidden sibling Finding under a custom Scenario
Case E: same Organization, unrelated user only
Case F: other Organization
```

The collection must include only authorized managed Cases, compute Case/Finding/Action factual progress correctly, classify deadlines correctly, and leak nothing from B/C/D-hidden/E/F.

The detail endpoint for Case A must expose the authorized factual drill-down and use the same captured `as_of` semantics.

The PR remains Draft and unmerged after this gate. M3.3 Final Architecture Review begins only after implementation and CI satisfy this document.
