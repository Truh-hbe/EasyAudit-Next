# M5.1 Architecture / Acceptance

Baseline: main@90d5a1a6ba447d59f0941e85890c4eee8b00aee1

This is a docs-only Gate. It selects the next executable slice; it is not implementation approval by itself.

## A. Scope and state proof

- The candidate starts from the verified main baseline.
- The state file names M5.1, the exact branch, this Gate and the accepted path scope.
- The PR contains only the declared Gate/status/roadmap files.
- The Gate check passes with no forbidden or out-of-scope paths.
- No executable source, migration, OpenAPI artifact, package lockfile or CI change is introduced.

## B. Domain boundary

- ReviewPlan remains cross-Scenario and organization-scoped.
- ReviewCase retains exact scenario_key and scenario_version.
- Scenario-specific fields remain Scenario-owned data.
- Plan membership does not introduce a second Case or workflow model.
- Case lifecycle remains Scenario-owned; M5.1 does not add Plan lifecycle.

## C. Authorization and identity

- Every plan read and mutation is organization-scoped.
- UUID-only lookup is not accepted as an authorization boundary.
- Authenticated Users and Departments remain the collaboration identities.
- Platform administration roles are not silently converted into business ownership.
- The client does not become authorization, recipient or lifecycle truth.

## D. Persistence and concurrency

- Existing ReviewPlan and ReviewCase invariants are preserved.
- Any new association or mutation has an explicit transaction boundary.
- Failed multi-write operations leave no partial plan/case state.
- Concurrent updates cannot silently overwrite a newer planning state.
- Append-only Activity remains the audit trail for formal business actions.

## E. API and query boundary

- Existing generic planning endpoint families are reused or their extension is justified.
- Organization-scoped query services remain the read-side authority.
- Generic application code contains no Scenario identity branches.
- Exact Scenario policy/version resolution is preserved and fails closed.
- UTC-aware planning timestamps remain mandatory where applicable.

## F. Product acceptance boundary

- The implementation must cover plan discovery, plan detail and its organized cases.
- Existing Process Review behavior remains green.
- Compliance Review remains discoverable through the same generic planning surface.
- Scenario-specific fields and interactions are delegated through exact-version adapters.
- Real FastAPI plus authenticated Playwright acceptance exercises the completed planning journey.

## G. Review and transition rule

Architecture / Acceptance review must return PASS with P1=0 and P2=0 before the state can move to IMPLEMENTATION.

After implementation, the final review must require exact-head GitHub Actions success, relevant PostgreSQL/API/browser acceptance, a fixed candidate SHA and explicit user merge authorization.

Nothing in this document authorizes M5.2 or any later milestone.