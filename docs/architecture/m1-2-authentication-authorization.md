# M1.2 — Authentication & Platform Authorization

M1.2 keeps a person/account separate from the method used to authenticate that person.

- `users` remains the platform identity and carries only `system_admin` or `ordinary_user`.
- `local_credentials` stores a normalized login name and an Argon2id password hash.
- `auth_sessions` stores only a SHA-256 hash of a random browser token.
- the browser receives a `Secure`, `HttpOnly`, `SameSite=Strict`, `__Host-` cookie.
- every authenticated request rejects expired/revoked sessions and inactive users.
- `platform_audit_events` records authentication and administration events separately from Review
  Core Activity and is append-only in PostgreSQL.

The first Organization and administrator are created interactively with
`easyaudit-next bootstrap-admin`; the command has no default password and refuses to run after an
Organization exists.

M1.2 does not introduce review workflow roles or business CRUD APIs.
