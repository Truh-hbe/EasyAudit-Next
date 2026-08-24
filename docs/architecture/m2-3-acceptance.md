# M2.3 Acceptance Gate

M2.3 is ready for architecture review only when CI proves:

- Alembic upgrades the complete PostgreSQL chain through `20260824_0007`;
- Finding create/list/get are organization-scoped and Scenario-authorized;
- Process Review Finding `scenario_data` is validated and persisted;
- FindingParticipant role and Actor type combinations follow the exact ScenarioVersion;
- participant User and Department targets are active and organization-local;
- direct owner/collaborator and responsible-department membership grant visibility;
- Department visibility does not grant Finding transition or participant-management authority;
- `issue` and `void(reason)` use the Scenario workflow;
- two concurrent transitions from the same old lifecycle yield one success, one conflict, and one
  transition Activity;
- lifecycle cannot be supplied on create or changed by ordinary PATCH;
- architecture and text guards still prevent Review Core from depending on a concrete Scenario;
  and
- all M1 and M2.2 PostgreSQL atomicity regressions remain green.

The PR remains Draft and unmerged after this gate. M2.4 does not begin until Final Architecture
Review explicitly releases M2.3.
