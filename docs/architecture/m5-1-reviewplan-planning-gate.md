# M5.1 — ReviewPlan Planning Surface Architecture Gate

Status: GATE_DRAFT. This document defines the architecture and acceptance boundary only. It does not authorize executable product changes.

Baseline: main@90d5a1a6ba447d59f0941e85890c4eee8b00aee1

## Goal

Select and freeze the smallest next product slice after M4: a coherent ReviewPlan planning surface that organizes ReviewCase work without creating a second planning model or moving Scenario truth into generic code.

## Current repository reality

ReviewPlan already exists as a cross-Scenario Core container with organization scope, title, planned start/end timestamps and creator identity. ReviewCase already references an optional plan and preserves its exact scenario key and version. Existing generic API/application/query paths provide create, list and get operations for plans and cases.

M5.1 should compose and extend this capability deliberately. It must not assume that a new entity, plan lifecycle or universal workflow engine is needed.

## Architecture decisions to freeze

1. ReviewPlan remains a generic cross-Scenario planning container. It does not interpret compliance_review or process_review business fields.
2. ReviewCase remains the owner of Scenario key, immutable Scenario version and Scenario-specific data. A plan may organize cases but cannot replace their Scenario identity.
3. The first planning surface uses the existing ReviewPlan and ReviewCase model. No universal template, form-builder, BPMN or runtime entity designer is introduced.
4. ReviewPlan lifecycle is not invented in M5.1. Case lifecycle and Scenario workflow remain authoritative.
5. Organization scope is mandatory for every plan read and mutation. A UUID alone is never an authorization boundary.
6. Generic planning authorization uses active organization users and existing business relationships. Platform roles are not reused as business ownership.
7. Generic application services and HTTP endpoint families remain Scenario-neutral. Scenario-specific planning data is validated by the exact Scenario policy where it belongs.
8. Planning queries must reuse the existing organization-scoped query and visibility boundaries. A new read-side truth is not introduced merely for the UI.
9. Planning mutations must preserve transaction and compare-and-swap guarantees already used by Review Core. Any new relation or mutation must define its atomicity and race behavior before implementation.
10. Product routing must continue to resolve Scenario behavior by exact key and version, with fail-closed behavior for unknown versions.

## Proposed product slice after Gate approval

- Browse organization-scoped ReviewPlans.
- Create and inspect a ReviewPlan with an explicit planning window.
- Discover the ReviewCases organized by a plan.
- Create or associate a ReviewCase through the existing Scenario version contract.
- Preserve authoritative server validation, visibility, lifecycle and Activity behavior.
- Provide a coherent Product Surface without duplicating Case, Finding or Scenario workflows.

The exact mutation shape, page-level interaction, pagination and error presentation are implementation decisions only after this Gate is accepted and must be specified in the implementation plan.

## Explicit non-goals

- No new generic Plan lifecycle.
- No automatic workflow/BPMN engine.
- No universal form or entity builder.
- No anonymous responsibility token.
- No cross-organization planning.
- No client-side authorization or lifecycle truth.
- No Compliance-specific copy of generic planning services.
- No M5.2 or later product scope in this slice.

## Gate exit criteria

The Architecture / Acceptance review may pass only when:

- the existing ReviewPlan boundary and current source are reconciled with this proposal;
- the API and Product Surface shape is explicit enough to implement without inventing domain truth;
- organization isolation, identity, authorization, exact Scenario versioning and transaction boundaries are explicit;
- required PostgreSQL, API, frontend and real-browser evidence is listed for the implementation phase;
- the implementation scope contains no unreviewed prerequisite;
- open P1 and P2 findings are zero; and
- the reviewer records PASS against this exact candidate.

Until then, the state remains GATE_DRAFT or GATE_REVIEW and executable paths remain forbidden by the machine-readable state.