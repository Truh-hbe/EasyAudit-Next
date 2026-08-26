# M2.3 Acceptance Gate

M2.3 is ready for architecture review only when CI proves:

- Alembic upgrades the complete PostgreSQL chain through `20260824_0007`;
- Finding create/list/get are organization-scoped and Scenario-authorized;
- Process Review Finding `scenario_data` is validated and persisted;
- FindingParticipant role and Actor type combinations follow the exact ScenarioVersion;
- participant User and Department targets are active and organization-local;
- direct owner/collaborator and responsible-department membership grant visibility;
- Department visibility does not grant Finding transition or participant-management authority;
- Review Core supplies Scenario-neutral Finding operation facts, including parent Case lifecycle,
  current Finding lifecycle, and persisted participant role presence;
- Process Review allows Finding creation only while the parent Case is `in_progress`;
- `draft`, `scheduled`, `cancelled`, `awaiting_closure`, and `closed` Cases cannot create new
  Findings;
- an existing open Finding may be issued or voided only while its Case is `in_progress` or
  `awaiting_closure`;
- `issue` requires both `owner` and `responsible_department` relationships before the Finding can
  enter `rectifying`;
- ordinary participant management is frozen for terminal `closed` and `voided` Findings;
- `issue` and `void(reason)` still use the Scenario workflow after operation invariants pass;
- scenario/business validation failures return 422 while CAS concurrency conflicts remain 409;
- PostgreSQL Finding fixtures advance the Case through `schedule` and `start` before creating a
  Finding;
- two concurrent transitions from the same old lifecycle yield one success, one conflict, and one
  transition Activity;
- lifecycle cannot be supplied on create or changed by ordinary PATCH;
- architecture and text guards still prevent Review Core from depending on a concrete Scenario;
  and
- all M1 and M2.2 PostgreSQL atomicity regressions remain green.

The PR remains Draft and unmerged after this gate. M2.4 does not begin until Final Architecture
Review explicitly releases M2.3.
