# M3.5.1 Credential Readiness — Backend Acceptance Gate

This Acceptance Gate defines the evidence required before the credential-readiness backend prerequisite may be merged and before M3.5.1 React implementation may start.

Baseline:

```text
main@50150287bd15f259595111f36aa6869c5977b9c9
```

The prerequisite Gate PR is documentation-only.

## Scope proof

The Gate PR itself must contain only:

```text
docs/architecture/m3-5-1-credential-readiness-backend.md
docs/architecture/m3-5-1-credential-readiness-acceptance.md
```

No executable backend or frontend change belongs in the Gate PR.

After Gate approval, the implementation must remain narrowly limited to Platform/API credential readiness, authentication/session persistence safety, OpenAPI, and tests.

Acceptance fails if implementation expands into Review Core, Workbench, Notification, Management, Reminder, Scenario, migrations without demonstrated need, CORS/CSRF redesign, JWT, MFA, forgot-password, or React code.

## Existing-contract counterexample

Acceptance must preserve and explicitly test the existing server semantics:

```text
admin creates ordinary local user
must_change_password defaults true
        ↓
POST /api/v1/auth/login
→ 200 + valid server Session
        ↓
AuthenticatedIdentity
→ succeeds
        ↓
BusinessIdentity
→ 403 Password change required before business APIs
```

Any implementation that changes the default to false, bypasses BusinessIdentity, or rejects login simply to avoid remediation fails Acceptance.

## Current-user posture acceptance

The server must expose the current authenticated user's credential requirement through the reviewed current-user contract.

At minimum:

```text
credential with must_change_password=true
→ authenticated current-user response exposes true

credential with must_change_password=false
→ exposes false
```

The value must be loaded from server persistence and must not be supplied by the client.

If the current authenticated user has no local credential, the password-change requirement for this local-credential mechanism must be reported as not required; attempting the local-password change command must fail explicitly rather than invent a credential.

## No 403 inference contract

Acceptance must prove the client does not need to discover password-change requirement by first calling a business API and receiving 403.

The backend current-user/bootstrap response is the primary discovery mechanism.

The existing BusinessIdentity 403 remains an independent enforcement backstop.

## Self-service command authorization

The password-change command must require:

```text
AuthenticatedIdentity
```

and must **not** require:

```text
BusinessIdentity
```

because a user with `must_change_password=true` must be able to satisfy the requirement while business APIs remain blocked.

The command must operate only on the authenticated user. Acceptance fails if the request body/path allows the caller to choose another target user ID.

## Current-password verification

At least one integration/API test must prove:

```text
valid Session
+ wrong current_password
→ password change rejected
→ password_hash unchanged
→ password_changed_at unchanged
→ must_change_password unchanged
→ current/other Sessions unchanged
→ no successful password-change audit fact
```

The failure must not be reported as Session expiry.

## Password policy acceptance

New password must satisfy the existing server password policy.

At minimum test:

```text
new password shorter than existing minimum
→ rejected
→ transaction has no credential/Session/audit success mutation
```

A new password equivalent to the current password must also be rejected so a user cannot clear `must_change_password` without genuinely changing the credential.

Frontend validation may assist later, but server validation is authoritative.

## PostgreSQL credential-row acceptance

The implementation must provide real PostgreSQL evidence that the final password security decision is made against a fresh locked `LocalCredential` row.

Password change must be equivalent to:

```text
SELECT LocalCredential
FOR UPDATE
+ fresh reload/populate_existing
        ↓
verify current password
        ↓
update credential
```

A unit test that mocks repository ordering is insufficient.

Successful local-password login must also participate in this credential-row serialization boundary immediately before Session issuance.

It may use an earlier coarse lookup/verification, but before creating a Session it must be equivalent to:

```text
SELECT LocalCredential
FOR UPDATE
+ fresh reload
        ↓
final password re-verification
        ↓
create AuthSession
```

Any equivalent implementation is acceptable; exact method names are not frozen.

## Concurrent password-change race acceptance

A dual-Session PostgreSQL test is mandatory.

Setup:

```text
same user
old password = P0
two concurrent requests A and B
both submit current_password=P0
A proposes P1
B proposes P2
```

Required result:

```text
exactly one change succeeds
winner commits first
loser acquires/reloads guarded credential
loser re-verifies P0 against new persisted hash
loser fails
```

Forbidden result:

```text
both requests validate stale P0
→ last writer wins silently
```

The final credential must match exactly one new password.

## Concurrent login versus password-change acceptance

A real PostgreSQL race between local-password login and password change is mandatory.

Setup:

```text
same user
old password = P0

A: password change P0 → P1
B: concurrent login using P0
```

Only these two serial outcomes are legal:

```text
B wins credential guard first
→ B final-verifies P0
→ Session B is created
→ A later acquires credential guard
→ A commits P1
→ A revokes Session B as a prior/other Session
```

or:

```text
A wins credential guard first
→ A commits P1
→ B waits
→ B reloads guarded credential
→ final P0 verification fails
→ no Session is created
```

Acceptance must reject this outcome:

```text
A commits P1
+
Session B created from stale P0 remains valid
```

The test must validate final Session usability, not merely row counts.

## Atomic credential readiness acceptance

On successful change the following must commit atomically:

```text
password_hash = hash(new_password)
password_changed_at = change timestamp
must_change_password = false
```

A failure injected after credential mutation but before Session/audit completion must roll back the whole request.

After rollback:

```text
old password still authenticates according to pre-request state
must_change_password remains true
Session semantics remain pre-request
no successful password-change audit fact persists
```

## Session repository monotonicity acceptance

Source review and PostgreSQL tests must prove that stale AuthSession snapshots cannot reverse committed security transitions.

Repository-level invariants:

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

stale snapshot carrying T0
→ cannot restore T0 after T1 commits
```

A generic whole-snapshot update that writes stale `revoked_at` or `token_hash` values back to the database fails Acceptance.

Exact repository method names are not frozen. Narrow guarded operations such as `touch_if_active`, `revoke_if_active`, and `rotate_current`, or equivalent SQL/CAS/row-lock semantics, are acceptable.

## Stale touch versus revocation acceptance

A real PostgreSQL counterexample test is mandatory.

Setup:

```text
Session B initially active

request B:
authenticate reads Session B
revoked_at = NULL

request A:
password change revokes Session B
→ COMMIT

request B:
attempts stale last_seen touch
```

Required result:

```text
Session B remains revoked
revoked_at remains the committed timestamp
future authentication with Session B fails
```

Forbidden result:

```text
stale touch writes revoked_at=NULL
→ Session B resurrects
```

The test must exercise actual repository/database behavior, not only a mocked application sequence.

## Current Session rotation acceptance

Successful password change must rotate the current Session token.

A real integration/API test must prove:

```text
old current cookie/token T0 is valid before change
password change succeeds
server issues new HttpOnly cookie token T1
T1 != T0
stored current Session token hash matches T1
T0 no longer authenticates after commit
T1 authenticates after commit
```

The current logical Session may retain its Session ID unless implementation review establishes an equivalent clean model, but the raw credential carried by the browser must rotate.

No raw T1 may appear in JSON response bodies, logs, audit metadata, or JavaScript-readable storage.

## Stale token snapshot versus rotation acceptance

A PostgreSQL/session-repository test must prove that a request holding a stale pre-rotation Session snapshot cannot restore the old token hash after rotation commits.

Setup conceptually:

```text
request B holds Session snapshot with token_hash(T0)

password change A
→ rotates current Session T0 → T1
→ COMMIT

request B
→ performs any later permitted Session persistence/touch operation
```

Required result:

```text
stored token_hash remains token_hash(T1)
T0 remains invalid
T1 remains valid
```

Forbidden result:

```text
stale snapshot update restores token_hash(T0)
```

If implementation prevents ordinary touch operations from writing `token_hash` at all, the test should prove that persistence contract directly.

## Cookie-property preservation

If password change reissues the Session cookie, response/browser evidence must preserve:

```text
name = __Host-easyaudit_session
Secure = true
HttpOnly = true
SameSite = Strict
Path = /
```

Acceptance fails if rotation introduces weaker cookie attributes.

## Other-session revocation acceptance

Create at least two active Sessions for the same user before password change.

After a successful change from Session A:

```text
Session A
→ rotated and remains valid through new token

Session B and every other previously active Session
→ revoked
→ cannot authenticate
```

Revocation must be server-side and transactionally coupled to password change.

No browser-local blacklist is acceptable.

## Cloned-old-token acceptance

Because current Session token rotation is part of the security boundary, acceptance must show that a copy of the pre-change current token cannot authenticate after commit.

This proves remediation does not leave a copied pre-remediation token valid merely because it represented the same Session ID.

## Audit acceptance

Successful password change must append a PlatformAudit fact equivalent to:

```text
auth.password_changed
actor_user_id = current user
target_user_id = current user
```

Other Session revocations must retain explicit append-only audit evidence according to the reviewed implementation.

Source/test review must prove audit metadata contains none of:

```text
current password
new password
password hash
raw old Session token
raw new Session token
```

Audit records remain append-only.

## Successful remediation journey

A full PostgreSQL-backed API test must prove:

```text
1. system_admin creates ordinary local user with default must_change_password=true
2. user logs in successfully
3. current-user response reports password-change requirement
4. direct BusinessIdentity-protected API is 403
5. user submits valid current password + valid different new password
6. credential mutation commits
7. current Session token rotates
8. other active Sessions revoke
9. current-user response now reports requirement=false
10. BusinessIdentity-protected API no longer fails because of credential readiness
11. old password no longer authenticates
12. new password authenticates
```

Business API access after step 10 remains subject to its normal business authorization; the test only needs to prove the password-change gate is no longer the reason for rejection.

## Transaction failure acceptance

At least one test must force a failure in the successful mutation transaction after guarded credential verification but before commit.

Acceptance requires no partial persistence of:

```text
new password hash
must_change_password=false
Session rotation
other-session revocations
password-changed audit event
```

The whole security transition is one transaction.

## No local credential acceptance

For an authenticated user with no `LocalCredential`:

```text
current-user posture
→ does not falsely require local password change

self-service local-password command
→ explicit unsupported/state-conflict response
→ no credential row auto-created
```

This Gate does not define SSO/external credential remediation.

## Error-semantics acceptance

Tests must keep Session loss distinct from credential errors:

```text
invalid/expired Session
→ 401

wrong current password
→ authenticated credential error, not 401 Session expiry

new password policy failure
→ validation error

same-as-current password
→ validation error

no local credential
→ explicit state conflict/unsupported path
```

Exact non-401 codes may be chosen in implementation, but they must be stable in OpenAPI/tests and usable by Product Surface without guessing.

## OpenAPI acceptance

Any current-user response extension and new password-change command must be reflected in OpenAPI.

Existing OpenAPI checks remain green.

No unrelated auth/token endpoints may appear.

## Repository-boundary acceptance

If `LocalCredentialRepository` or AuthSession persistence contracts change, the new surface must remain narrow and security-specific.

Expected credential capabilities are equivalent to:

```text
get_by_user_id
lock_by_user_id
update
```

Expected Session capabilities are equivalent to narrow guarded mutations such as:

```text
touch active Session
revoke active Session
rotate current Session token
```

Acceptance rejects a generic credential/session CRUD service, API-layer SQL bypassing application/domain boundaries, or whole-snapshot Session persistence that can replay stale security fields.

## BusinessIdentity preservation acceptance

Source review must confirm `require_business_identity()` remains server-authoritative and is not changed to trust a frontend flag.

Required regression tests:

```text
must_change_password=true
→ BusinessIdentity 403

must_change_password=false
→ credential gate passes
```

No `system_admin` exception is introduced unless separately reviewed. A system administrator with a password-change requirement is still subject to the credential security posture where BusinessIdentity is used.

## Login/logout compatibility acceptance

Existing external behavior remains compatible:

```text
login for must-change user still succeeds
existing Secure HttpOnly Session created
logout still revokes current Session and clears cookie
```

Internally, successful local-password login must add the guarded final credential re-verification required by this Gate.

Password change must not introduce a parallel token type or alternate login path.

## No migration acceptance

Because the required persisted fields already exist, the expected implementation contains no Alembic migration.

If implementation discovers a real schema requirement, work stops and the Gate is amended before adding a migration.

## Existing CI preservation

The implementation fixed head must retain:

```text
Ruff
mypy
architecture check
OpenAPI check
Alembic upgrade
PostgreSQL pytest
```

and add the new credential/session concurrency tests to the normal suite.

## Fixed-head review evidence

The backend prerequisite cannot pass Final Review without:

```text
exact implementation head SHA
PR open/mergeable/unmerged state during review
exact base SHA
full changed-file review
CI completed/success on exact head
real PostgreSQL password-change race evidence
real PostgreSQL login-vs-password-change evidence
real PostgreSQL stale-touch-vs-revoke evidence
stale-token-vs-rotation evidence
successful remediation journey evidence
Session rotation + other-session revocation evidence
scope proof against this Gate
```

## Explicit non-goals

Acceptance must not reward adding:

```text
forgot-password flow
email/SMS reset
admin reset UI
password history
password expiry schedule
MFA
OIDC/SSO
refresh/access tokens
JWT
remember-me
cross-origin auth
CORS/CSRF redesign
React code
Review business semantics
new Authentication Aggregate
```

## Final invariant checklist

The prerequisite cannot pass unless all are true:

```text
server exposes current user's credential requirement
must_change_password default remains true for normal admin-created local user
valid Session may coexist with requirement=true
BusinessIdentity remains blocked while true
password-change command uses AuthenticatedIdentity, not BusinessIdentity
caller can change only own local credential
current password is re-verified against a PostgreSQL-locked fresh credential row
successful local-password Session issuance shares the credential-row serialization boundary
same-as-current password cannot clear requirement
hash + password_changed_at + requirement=false commit atomically
concurrent password-change race has exactly one winner
concurrent old-password login cannot create a surviving stale-P0 Session
current Session token rotates
old current token becomes invalid
other active Sessions revoke
stale Session touch cannot clear revoked_at
stale Session snapshot cannot restore an old token_hash
Secure/HttpOnly/Strict cookie semantics remain unchanged
audit facts are append-only and contain no secrets
rollback cannot leave partial readiness state
server reports requirement=false only after committed success
BusinessIdentity credential gate opens only after server state changes
no frontend or token-model workaround is introduced
```

This Gate exists solely to make the already-present Platform Core credential safety contract fully usable by M3.5.1 Product Surface.