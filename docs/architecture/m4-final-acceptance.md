# M4 Final — Second Scenario Validation Completion Acceptance

Baseline:

```text
main@27e750c4901c8abd81b6a55703cd664c237e057e
```

This Acceptance belongs to `m4-final-second-scenario-validation.md`.

The PR is **docs-only**. It verifies that the already-merged M4.1 implementation has satisfied the frozen M4 objective and that no artificial additional M4 slice is needed.

## A. Scope proof

The branch diff must contain exactly:

```text
docs/architecture/roadmap.md
docs/architecture/m4-final-second-scenario-validation.md
docs/architecture/m4-final-acceptance.md
```

Acceptance fails if the PR contains executable source, migration, generated OpenAPI, package/lockfile or CI/workflow changes.

## B. Baseline proof

The branch must start exactly from the M4.1 merge commit:

```text
27e750c4901c8abd81b6a55703cd664c237e057e
```

The M4.1 merge commit must remain verified as:

```text
tree:
047553fa7a340f52d1845923a4529fa5546b9db3

parents:
c54600d52e0ace0fa60eb982261ca69dceb416b7
c02e6901a900807db1b3a51ed36f68e479af63d3
```

PR #26 must be `closed / merged / non-Draft` with the same merge commit.

## C. Exact-head CI evidence

The Final Review candidate for M4.1 must remain:

```text
c02e6901a900807db1b3a51ed36f68e479af63d3
```

with:

```text
CI #391
completed / success
```

Acceptance fails if the M4 completion claim relies on a different or later unreviewed executable head.

## D. Material second-Scenario proof

The merged implementation must contain exact:

```text
compliance_review@1
```

and materially different behavior:

```text
observation
OPEN --accept_observation--> CLOSED
```

without creating a synthetic ActionItem or rectification Submission.

The same command must remain invalid for `process_review@1`.

A Compliance `nonconformity` must continue to use the existing rectification family and require persisted responsibility relationships before issue.

## E. Scenario-specific data boundary

Compliance-specific fields must remain Scenario data rather than new generic columns:

Case:

```text
standard_reference
scope_summary
```

Finding:

```text
criterion_reference
finding_type
```

No new generic lifecycle value is required for observation/nonconformity semantics.

## F. Generic backend reuse

Acceptance requires the merged implementation to prove:

```text
same Review Core entities
same generic application services
same generic HTTP endpoint families
same ScenarioRegistry composition path
```

Generic Review Core/application code must not contain Compliance identity branches.

The direct Finding transition seam must remain Scenario-owned for decision semantics while generic code owns authorization execution, CAS persistence and generic Activity persistence.

## G. Non-disclosure and authorization proof

Before an exact Scenario direct transition decision can reveal validation facts, generic Finding visibility authorization must fail closed for an invisible actor.

Final mutation authorization must still use the permission returned by the exact Scenario decision.

## H. PostgreSQL integrity and race proof

Real PostgreSQL acceptance must already prove:

- cross-Organization persisted relationships are rejected; and
- Case close racing `accept_observation` never commits a closed Case with a non-terminal child Finding.

No new lock architecture is required if the existing serialization proof passed.

## I. M3 reuse proof

Compliance resources must already be proven through the existing:

```text
Workbench
Management
Manual Nudge
Notification
```

No Compliance-specific read-side/service family is acceptable.

Recipient selection remains server/Scenario-owned; React does not submit recipient IDs.

## J. Product Surface proof

The generic Finding page must delegate Scenario-specific interaction presentation through the centralized exact-version adapter boundary.

Production adapter resolution must include exact:

```text
process_review@1
compliance_review@1
```

and reject/fail closed for unknown exact versions rather than falling back by key/latest/nearest.

Scenario adapters may construct Scenario command payloads but must not become client-side authorization/workflow truth.

## K. Real browser proof

The M4.1 exact-head CI must include real PostgreSQL + FastAPI + authenticated Playwright acceptance for both existing Process Review and Compliance behavior.

The Compliance journey must prove at minimum:

```text
Workbench discovery
→ shared ReviewCase route
→ exact Compliance fields
→ shared Finding route
→ observation without synthetic Action/Submission
→ shared transition endpoint accept_observation
→ authoritative CLOSED
→ generic finding.transitioned history
```

## L. M4 completion rule

M4 may be frozen complete only if all original roadmap acceptance requirements are already met by the merged M4.1 implementation.

If any original M4 requirement remains unproven, this finalization Gate fails and a real additional slice must be defined from the missing requirement.

If none remains, the correct result is:

```text
M4 Second Scenario Validation
COMPLETE
```

and **no M4.2 is created solely for numbering continuity**.

## M. Roadmap rebaseline

`roadmap.md` must:

- update current baseline to the M4.1 merge commit;
- move M4 from `Next` to `Completed`;
- summarize the exact second-Scenario proof and generic reuse; and
- state that the post-M4 milestone is selected only by a separate Gate.

This PR must not define executable post-M4 scope.

## N. PR discipline

Until this finalization Gate is reviewed, the PR remains:

```text
open
Draft
unmerged
```

No executable work begins from this branch.
