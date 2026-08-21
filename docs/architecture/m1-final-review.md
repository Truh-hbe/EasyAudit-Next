# M1 Final Review

M1 is accepted only as a platform foundation. Process-review workflow and Review Core business
HTTP writes remain M2 scope.

| Acceptance item | M1 evidence |
| --- | --- |
| Fresh database | CI upgrades PostgreSQL 17 from an empty database through Alembic `0005`. |
| Bootstrap | Interactive CLI creates the first Organization, system admin, Argon2id credential, and audit event; a second run is rejected. |
| Password | `pwdlib[argon2]`; plaintext is never persisted. |
| Login/session | Random browser token, SHA-256 database hash, server-side expiry and revocation. |
| Cookie | Fixed `__Host-easyaudit_session`, `Secure`, `HttpOnly`, `SameSite=Strict`, path `/`. |
| Disable user | Authentication checks User activity on every request and admin disable revokes existing sessions. |
| Platform permission | Only `system_admin` reaches admin dependencies; an Organization row lock serializes admin removal so the final active admin cannot be disabled or demoted, including under concurrent transactions. |
| Department | Composite Organization foreign key plus service and trigger cycle rejection. |
| Scenario | Organization catalog and immutable exact versions; Policy behavior stays in code. |
| Review Core | UUID records, typed strong foreign keys, and organization-aware composite relations. |
| Actor XOR | FindingParticipant and ActionAssignee require exactly one User or Department. |
| Activity | Exactly one typed target; PostgreSQL rejects UPDATE and DELETE. |
| Platform audit | Separate append-only events for bootstrap, authentication, users, departments, and session revocation. |
| OpenAPI/CI | Stable operation checks, ruff, strict mypy, architecture guard, Alembic, PostgreSQL tests, and pytest. |

The supported merge order is M1.1, M1.2, M1.3, then M1.4/Final Polish. After that sequence lands,
the next implementation milestone is M2 Process Review.

## M2 entry gates

These items do not block the M1 persistence foundation, but must be completed before Review Core
business HTTP APIs are opened:

1. Make `must_change_password` enforceable through a restricted first-login session and password
   change flow, or stop presenting the flag as an enforced control until that flow exists.
2. Make Review Core repository reads Organization-scoped by default, for example
   `get_case(organization_id, case_id)`, before handlers can return those records.

M2 should also introduce a stable API error contract: detailed SQLAlchemy/PostgreSQL integrity
errors remain in internal logs, while clients receive bounded business error codes and messages.
