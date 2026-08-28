# M3.5.1 Credential Readiness — Backend Prerequisite Gate

This Gate exists because the merged Platform Core permits a valid authenticated Session while `LocalCredential.must_change_password=true`, and `BusinessIdentity` intentionally rejects business APIs until that requirement is cleared.

Baseline:

```text
main@50150287bd15f259595111f36aa6869c5977b9c9
```

This Gate PR is documentation-only. It must not add executable backend code, React code, migrations, CORS/CSRF changes, new token models, or Product Surface implementation before review.

## Proven existing contract

Current administrator user creation defaults to:

```text
must_change_password = true
```

Current authentication semantics are:

```text
POST /api/v1/auth/login
→ valid credentials may create a Session even when must_change_password=true

GET /api/v1/me
→ AuthenticatedIdentity
→ currently returns user metadata only

BusinessIdentity
→ re-reads LocalCredential
→ if must_change_password=true:
   403 Password change required before business APIs
```

Therefore:

```text
authenticated
≠ credential ready for business access
```

The backend prerequisite must expose and remediate that server-owned fact without weakening the existing Session or BusinessIdentity model.

## Goal

Establish the minimum backend contract required for normally provisioned users to become credential-ready while closing every concurrent path that can create, revive, or restore a pre-remediation Session credential.

```text
current authenticated user
        ↓
server exposes credential requirement
        ↓
user performs authenticated self-service password change
        ↓
credential mutation participates in PostgreSQL serialization
        ↓
current password re-verified against guarded row
        ↓
new password validated
        ↓
password hash + password_changed_at + must_change_password=false
updated atomically
        ↓
current Session token rotated
other Sessions revoked
        ↓
Session persistence remains monotonic under concurrent touch/revoke/rotate
        ↓
append-only PlatformAudit facts
        ↓
BusinessIdentity becomes available
```

The security boundary is not limited to two concurrent password-change writers. It must also cover successful login Session issuance and all Session persistence paths that can race with revoke/rotate.

## Scope

The executable implementation after Gate approval may modify only the Platform/API surfaces needed for:

```text
current-user credential posture
self-service local-password change
LocalCredential update/locking support
successful login Session issuance serialization
current Session rotation
other Session revocation
concurrent Session touch safety
PlatformAudit facts
OpenAPI contracts
tests
```

No Review Core, Workbench, Notification, Management, Reminder, Scenario, lifecycle, migration, CORS, CSRF, JWT, refresh-token, or frontend code is in scope.

No schema migration should be needed because `LocalCredential.password_hash`, `password_changed_at`, and `must_change_password` already exist and AuthSession already stores the facts required for token rotation/revocation.

## Current-user credential posture contract

The server must provide an authenticated current-user response that includes the credential requirement needed by Product Surface.

The preferred contract is to evolve the `/api/v1/me` response specifically for current-user bootstrap rather than creating a parallel frontend-auth authority.

Conceptually:

```json
{
  "id": "...",
  "organization_id": "...",
  "display_name": "...",
  "platform_role": "ordinary_user",
  "primary_department_id": "...",
  "is_active": true,
  "must_change_password": true
}
```

Exact Pydantic type naming is an implementation detail, but the response must be server-derived from the current authenticated user's `LocalCredential` in the request transaction.

Rules:

```text
LocalCredential exists + must_change_password=true
→ response true

LocalCredential exists + false
→ response false

no LocalCredential
→ false for this requirement
```

The Product Surface must not infer the value from a 403 or from `platform_role`.

## Self-service password-change command

The backend must add one authenticated current-user command for changing the caller's own local password.

The endpoint spelling may be chosen during implementation, but the semantics are frozen:

```text
AuthenticatedIdentity required
BusinessIdentity NOT required
```

This is necessary because a password-change-required user is intentionally blocked by `BusinessIdentity`.

The command accepts at least:

```text
current_password
new_password
```

It changes only the authenticated user's own `LocalCredential` and must not accept a target user ID from the client.

## Password validation

The command must:

```text
verify current_password against the guarded persisted credential
validate new_password against the existing Platform password policy
reject new_password if it is effectively the same as the current password
```

The initial M1 policy remains authoritative unless a separate password-policy Gate changes it.

M3.5.1 must not introduce a second frontend password policy.

## Credential-row serialization boundary

A password change is a write-side security mutation and must not use a stale credential snapshot. A successful login also crosses the same credential security boundary because it creates a new server Session from a password assertion.

The following operations must therefore share a PostgreSQL credential-row serialization boundary at their final security decision point:

```text
1. password change
2. successful local-password login immediately before Session issuance
```

Password change must perform an equivalent of:

```text
SELECT LocalCredential
FOR UPDATE
+ populate_existing / equivalent fresh reload
        ↓
verify current_password against guarded password_hash
        ↓
validate new password
        ↓
update guarded credential
```

Successful login may perform a coarse lookup/verification before the lock for efficiency, but before creating a Session it must perform an equivalent guarded final step:

```text
coarse login lookup / optional preliminary verification
        ↓
SELECT LocalCredential
FOR UPDATE
+ fresh reload
        ↓
final password re-verification against guarded password_hash
        ↓
create AuthSession
```

Any implementation with equivalent safety is acceptable. Exact repository method names are not frozen.

The required race semantics are:

```text
login wins credential guard first
→ Session is created
→ password change later acquires the guard
→ password change revokes that Session if it is not the current remediation Session

password change wins credential guard first
→ login waits
→ login reloads the new hash
→ stale old password fails
→ no Session is created
```

Forbidden:

```text
old password P0 validated from stale credential
→ password change commits P1
→ a Session created from stale P0 remains valid
```

A normal PostgreSQL MVCC `SELECT` does not automatically wait for another transaction's `SELECT ... FOR UPDATE`; locking only the password-change writer is therefore insufficient.

## Atomic credential update

Within one transaction, successful password change must update exactly the credential facts that define readiness:

```text
password_hash = hash(new_password)
password_changed_at = now
must_change_password = false
```

The requirement must not be cleared before the password hash update is durable.

If password update, Session handling, or audit persistence fails, the transaction rolls back and `must_change_password` remains unchanged.

React or any client cannot clear this field.

## Session security invariants

Because password remediation rotates/revokes server Sessions, Session persistence must be safe under stale concurrent request snapshots.

A stale AuthSession object must never be able to reverse a committed security transition.

The repository/persistence layer must enforce at least these monotonic invariants:

```text
revoked_at:
NULL → timestamp
allowed

timestamp → NULL
FORBIDDEN
```

and:

```text
committed token rotation:
T0 hash → T1 hash
allowed through the guarded rotation operation

stale snapshot carrying T0 hash
→ must never restore T0 after T1 commits
```

A normal request touch must update only the facts it owns and must not replay stale security fields.

Conceptually acceptable shapes include:

```text
touch_if_active(...)
revoke_if_active(...)
rotate_current(...)
```

or guarded SQL/CAS/row-lock equivalents.

Exact method names are implementation details. What is frozen is the persistence invariant: stale snapshots cannot clear `revoked_at`, restore an old `token_hash`, or otherwise undo committed rotation/revocation.

## Concurrent Session touch

Authentication/touch is a separate concurrent entry point from password change.

The implementation must prevent this race:

```text
request B
→ reads Session B with revoked_at=NULL

password change A
→ revokes Session B
→ commit

request B
→ later attempts last_seen touch using stale Session snapshot
```

Required result:

```text
Session B remains revoked
```

Forbidden result:

```text
stale touch writes revoked_at=NULL
→ Session B resurrected
```

The same principle applies to token rotation: a stale request snapshot containing the old token hash must never overwrite a committed rotated token hash.

## Session semantics after password change

On success:

```text
current Session
→ remains the logical current Session
→ token is rotated to a new cryptographically random value
→ server stores only the new token hash
→ response reissues __Host-easyaudit_session
   with Secure / HttpOnly / SameSite=Strict / Path=/

all other active Sessions for the same user
→ revoked in the same transaction
```

Why rotation is required:

```text
old browser cookie / copied current-session token
→ must no longer authenticate after password change
```

The endpoint response must not expose the new raw token to JavaScript except through the existing HttpOnly `Set-Cookie` mechanism.

## Session concurrency boundary

Credential readiness is one security transition spanning credential and Session state. It must be safe against:

```text
1. password mutation
2. successful Session issuance
3. current Session rotation
4. other Session revocation
5. concurrent Session touch
```

This does **not** require a new giant Authentication Aggregate or one global lock.

The narrow required model is:

```text
Credential:
final successful local-password login verification
and password change
→ share PostgreSQL credential-row serialization

Session:
touch / revoke / rotate
→ use monotonic or guarded persistence semantics
→ stale snapshots cannot undo revoke/rotate
```

The current AuthSession participating in rotation must be the authenticated request Session. Other active Sessions are revoked server-side.

After commit:

```text
old current token → invalid
new current token → valid
other prior active session tokens → invalid
```

No frontend blacklist or local revocation truth is allowed.

## Platform audit semantics

Password change is a platform security fact.

The successful transaction must append an audit event equivalent to:

```text
auth.password_changed
actor_user_id = current user
target_user_id = current user
```

Other Session revocations must continue to produce the existing append-only session-revocation audit facts or an equally explicit reviewed equivalent.

Audit events must not include:

```text
current password
new password
password hash
raw Session token
```

Failed current-password validation must not mutate the credential or clear the requirement. Whether a dedicated failure audit event is added may be decided in implementation, but it must not leak secret input.

## Error semantics

The command must distinguish at least:

```text
401
→ Session invalid / unauthenticated

current password invalid
→ authenticated credential-remediation error
→ MUST NOT be treated as Session expiry

new password violates policy / same as current
→ validation error

no local credential for current user
→ explicit state conflict / unsupported credential path
```

Exact non-401 status codes may be frozen in implementation review, but the Product Surface must be able to distinguish Session loss from password-change validation failure.

## BusinessIdentity remains unchanged in authority

This prerequisite must **not** weaken:

```text
require_business_identity()
```

While `must_change_password=true`:

```text
business API
→ still 403
```

After the guarded server transaction commits with `must_change_password=false` and the request has the rotated valid Session:

```text
business API
→ proceeds to normal business authorization
```

No route-specific bypass is permitted.

## API compatibility

The existing login behavior remains valid:

```text
must_change_password=true
→ login may succeed
→ Session may exist
```

The backend must not change login into a special frontend token or silently reject such users solely to avoid building remediation.

The only required login change is security-internal: successful local-password Session issuance must perform guarded final credential re-verification before Session creation.

`POST /api/v1/auth/logout` and existing Session cookie semantics remain unchanged except that password change may reissue the same cookie name with a rotated value.

## Transaction boundary

The successful self-service change must be one request transaction covering:

```text
credential row lock
current-password verification
credential update
current Session token rotation
other Session revocation
audit append(s)
commit
```

No partial success is acceptable.

The Session repository operations used inside this transaction must preserve the monotonic invariants defined above under concurrent requests.

## Explicit non-goals

This prerequisite does not add:

```text
forgot-password / email reset
admin password reset UI
password history tables
password expiration schedules
MFA
SSO/OIDC
JWT/access/refresh tokens
cross-origin browser auth
CORS expansion
CSRF redesign
remember-me sessions
credential recovery codes
new platform roles
Review business permissions
React implementation
new Authentication Aggregate
```

Those require separate Gates if ever needed.

## Implementation shape after Gate approval

A narrow executable implementation is expected to touch only surfaces equivalent to:

```text
platform/application authentication / dedicated credential service
platform/domain repository contracts for guarded credential and Session mutations
platform/persistence credential/session repositories
api current-user/password-change contracts
api router/dependencies only as necessary
unit/integration/API/PostgreSQL concurrency tests
OpenAPI snapshot/checks if generated contract changes
```

No migration or unrelated module expansion should appear without a new Gate.

## Final architecture invariant

The prerequisite succeeds when all of this is true:

```text
valid Session + must_change_password=true
→ server explicitly reports requirement
→ BusinessIdentity remains blocked
→ authenticated user changes own password
→ PostgreSQL serializes password change against successful login Session issuance
→ old password cannot escape through a concurrent stale login
→ password hash/password_changed_at/requirement update atomically
→ current Session token rotates
→ other Sessions revoke
→ stale Session touch cannot resurrect a revoked Session
→ stale Session snapshot cannot restore an old rotated token
→ append-only audit records security change
→ server reports requirement=false
→ BusinessIdentity becomes available
```

The server remains the sole authority for Session validity, credential readiness, and business access.