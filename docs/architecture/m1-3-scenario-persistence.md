# M1.3 — Scenario Persistence

M1.3 persists organization-specific Scenario availability without moving domain behavior into
PostgreSQL.

- `scenarios` records the key, display name, and active flag for one Organization.
- `scenario_versions` records immutable published versions and carries `organization_id` for
  composite foreign keys used by Review Core.
- `ScenarioRegistry` remains the source of `validate_case_input`, case roles, and finding roles.
- `ScenarioCatalogService.publish` requires the exact code Policy before writing a publication.
- PostgreSQL rejects updates and deletes of published versions.

No authentication endpoints or review workflow APIs are introduced in this stage.
