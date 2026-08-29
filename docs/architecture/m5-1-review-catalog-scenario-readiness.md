# M5.1 Review Catalog and Scenario Readiness

## Gate status

This is the independently executable M5.1 Architecture Gate. It is reviewed
against the M5 parent charter but does not authorize M5.2 or later work.

## Goal

Make a clean installation able to publish the two code-known exact scenarios and
make those scenarios discoverable to an authenticated business user who can
actually create a case with them.

M5.1 also establishes the exact-version frontend Case-create adapter seam that
M5.2 will consume. It does not implement the planning wizard, team management,
administrator UI, credential recovery, deployment, or a dynamic form engine.

## Architecture

```text
code Scenario Registry
  -> operator publishes exact key/version
  -> existing ScenarioCatalogService
  -> persisted Scenario and ScenarioVersion
  -> authenticated review catalog query
  -> exact frontend Case-create adapter
```

The review catalog is a small projection of the intersection of:

- active persisted Scenario in the actor's organization;
- exact published ScenarioVersion;
- exact code Registry policy;
- current actor's exact Case-creation authorization.

The catalog must not expose workflow transitions, authorization expressions,
role formulas, dynamic JSON form schemas, recipient semantics, or a latest
scenario choice. It is not a second scenario truth.

## Operator publication contract

Add a narrow operator command equivalent to:

```text
easyaudit-next publish-scenario \
  --organization-id <UUID> \
  --key process_review \
  --version 1
```

The command must require an explicit organization ID, resolve the exact code
Registry policy, and delegate publication semantics to the existing
`ScenarioCatalogService`. It must fail deterministically for an unknown
organization, unknown Registry version, or duplicate exact publication. It must
not accept runtime policy definitions, select a latest version, or silently
convert duplicates into success.

The equivalent command must publish `compliance_review@1` as well.

## Business catalog contract

Add the authenticated endpoint:

```text
GET /api/v1/review-catalog
```

Its stable response item contains only:

```json
{
  "scenario_key": "process_review",
  "scenario_version": 1,
  "display_name": "Process Review"
}
```

The operation must use the existing business identity dependency, preserve
must-change-password behavior, enforce organization isolation, and return items
in deterministic order. Missing exact Registry policy is fail-closed; no nearby,
latest, or key-only fallback is permitted.

## Frontend adapter contract

Extend the exact-version `ScenarioCaseAdapter` in `web/src/scenarios/registry.ts`
with the Case-create presentation/payload seam:

- `CaseCreateFields`;
- `buildCaseScenarioData`;

Case member role-selection and role-presentation metadata is deferred to M5.3
and is not part of M5.1 implementation.

The adapter may own field rendering and payload construction. It must not own
authorization methods or business truth. M5.1 adds exact adapters for:

- `process_review@1`: `area_code`, `review_type`;
- `compliance_review@1`: `standard_reference`, `scope_summary`.

The backend remains responsible for authoritative validation when M5.2 later
submits a ReviewCase.

## Scope and expected persistence

Allowed implementation areas after this Gate passes are the CLI/composition,
catalog query/API contracts, exact frontend adapters, OpenAPI operation baseline,
and their focused tests. Existing domain persistence models and business
authorization semantics should be reused. No migration is expected or
pre-approved; if implementation proves that a migration is genuinely required,
stop and revise this Gate.

## Acceptance outline

M5.1 is complete only when the acceptance document is satisfied, including:

- clean migration and bootstrap followed by exact publication of both scenarios;
- duplicate and unknown-version publication failures;
- authenticated catalog returns both exact versions and no extra truth;
- inactive, unpublished, unknown, and cross-organization entries are absent;
- must-change-password users remain blocked by existing identity semantics;
- exact adapters render and build the two required payload shapes;
- unsupported exact versions fail closed;
- all new browser/API tests are wired into the repository's canonical CI command.
