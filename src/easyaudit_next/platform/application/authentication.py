from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from uuid import uuid4

from pwdlib import PasswordHash

from easyaudit_next.platform.application.password_policy import validate_local_password
from easyaudit_next.platform.domain.ids import AuthSessionId, PlatformAuditEventId, UserId
from easyaudit_next.platform.domain.models import (
    AuthSession,
    LocalCredential,
    PlatformAuditEvent,
    User,
)
from easyaudit_next.platform.domain.repositories import (
    AuthSessionRepository,
    LocalCredentialRepository,
    PlatformAuditRepository,
    UserRepository,
)

_DEFAULT_PASSWORD_HASH = PasswordHash.recommended()
_DUMMY_PASSWORD_HASH = _DEFAULT_PASSWORD_HASH.hash("not-a-real-user-password")


class InvalidCredentialsError(ValueError):
    """Login credentials are invalid without revealing which field failed."""


class InvalidSessionError(ValueError):
    """The browser session is absent, expired, revoked, or belongs to an inactive user."""


class InvalidCurrentPasswordError(ValueError):
    """The authenticated user's current local password did not verify."""


class PasswordReuseError(ValueError):
    """The proposed local password is equivalent to the current password."""


class LocalCredentialUnavailableError(LookupError):
    """The authenticated user has no supported local credential to remediate."""


@dataclass(frozen=True, slots=True)
class LoginResult:
    token: str
    auth_session: AuthSession
    user: User


@dataclass(frozen=True, slots=True)
class PasswordChangeResult:
    token: str
    auth_session: AuthSession
    user: User


class AuthenticationService:
    def __init__(
        self,
        credentials: LocalCredentialRepository,
        sessions: AuthSessionRepository,
        users: UserRepository,
        audit: PlatformAuditRepository,
        *,
        session_ttl: timedelta = timedelta(hours=12),
        touch_interval: timedelta = timedelta(0),
        password_hash: PasswordHash | None = None,
    ) -> None:
        self._credentials = credentials
        self._sessions = sessions
        self._users = users
        self._audit = audit
        self._session_ttl = session_ttl
        self._touch_interval = touch_interval
        self._password_hash = password_hash or _DEFAULT_PASSWORD_HASH
        self._dummy_hash = _DUMMY_PASSWORD_HASH

    def login(
        self,
        login_name: str,
        password: str,
        *,
        now: datetime | None = None,
    ) -> LoginResult:
        current_time = now or datetime.now(UTC)
        normalized_login = login_name.strip().lower()
        coarse_credential = self._credentials.get_by_login_name(normalized_login)
        coarse_matches = self._password_hash.verify(
            password,
            coarse_credential.password_hash if coarse_credential is not None else self._dummy_hash,
        )
        if coarse_credential is None or not coarse_matches:
            self._audit_login_failed(coarse_credential, normalized_login, current_time)
            raise InvalidCredentialsError("Invalid login name or password")

        credential = self._credentials.lock_by_login_name(normalized_login)
        final_matches = self._password_hash.verify(
            password,
            credential.password_hash if credential is not None else self._dummy_hash,
        )
        user = self._users.get(credential.user_id) if credential is not None else None
        if credential is None or not final_matches or user is None or not user.is_active:
            self._audit_login_failed(
                credential or coarse_credential,
                normalized_login,
                current_time,
            )
            raise InvalidCredentialsError("Invalid login name or password")

        token = token_urlsafe(32)
        auth_session = AuthSession(
            id=AuthSessionId(uuid4()),
            organization_id=user.organization_id,
            user_id=user.id,
            token_hash=self.hash_token(token),
            expires_at=current_time + self._session_ttl,
            created_at=current_time,
            last_seen_at=current_time,
        )
        self._sessions.add(auth_session)
        self._audit.add(
            PlatformAuditEvent(
                id=PlatformAuditEventId(uuid4()),
                organization_id=user.organization_id,
                actor_user_id=user.id,
                target_user_id=user.id,
                target_session_id=auth_session.id,
                event_type="auth.login_succeeded",
                occurred_at=current_time,
            )
        )
        return LoginResult(token=token, auth_session=auth_session, user=user)

    def authenticate(self, token: str, *, now: datetime | None = None) -> tuple[AuthSession, User]:
        current_time = now or datetime.now(UTC)
        auth_session = self._sessions.get_by_token_hash(self.hash_token(token))
        if (
            auth_session is None
            or auth_session.revoked_at is not None
            or auth_session.expires_at <= current_time
        ):
            raise InvalidSessionError("Session is invalid")
        user = self._users.get(auth_session.user_id)
        if user is None or not user.is_active:
            raise InvalidSessionError("Session is invalid")
        return auth_session, user

    def touch(self, auth_session: AuthSession, *, now: datetime | None = None) -> None:
        current_time = now or datetime.now(UTC)
        seen = auth_session.last_seen_at
        if seen is not None and seen >= current_time - self._touch_interval:
            return  # touched recently: no statement at all. The SQL guard covers stale snapshots.
        self._sessions.touch_if_active(
            auth_session.id,
            auth_session.token_hash,
            current_time,
            min_interval=self._touch_interval,
        )

    def logout(self, auth_session: AuthSession, user: User, *, now: datetime | None = None) -> None:
        current_time = now or datetime.now(UTC)
        if self._sessions.revoke_if_active(auth_session.id, current_time):
            self._audit.add(
                PlatformAuditEvent(
                    id=PlatformAuditEventId(uuid4()),
                    organization_id=user.organization_id,
                    actor_user_id=user.id,
                    target_session_id=auth_session.id,
                    event_type="auth.session_revoked",
                    occurred_at=current_time,
                )
            )

    def revoke_user_sessions(
        self,
        user_id: UserId,
        *,
        actor_user_id: UserId,
        now: datetime | None = None,
    ) -> None:
        current_time = now or datetime.now(UTC)
        user = self._users.get(user_id)
        if user is None:
            raise LookupError(f"User {user_id} does not exist")
        for auth_session in self._sessions.list_for_user(user_id):
            if self._sessions.revoke_if_active(auth_session.id, current_time):
                self._audit_session_revoked(user, auth_session.id, actor_user_id, current_time)

    def change_password(
        self,
        auth_session: AuthSession,
        user: User,
        current_password: str,
        new_password: str,
        *,
        now: datetime | None = None,
    ) -> PasswordChangeResult:
        current_time = now or datetime.now(UTC)
        if (
            auth_session.user_id != user.id
            or auth_session.organization_id != user.organization_id
        ):
            raise InvalidSessionError("Session is invalid")

        credential = self._credentials.lock_by_user_id(user.id)
        if credential is None or credential.organization_id != user.organization_id:
            raise LocalCredentialUnavailableError("Local credential is unavailable")
        if not self._password_hash.verify(current_password, credential.password_hash):
            raise InvalidCurrentPasswordError("Current password is invalid")

        validate_local_password(new_password)
        if self._password_hash.verify(new_password, credential.password_hash):
            raise PasswordReuseError("New password must differ from current password")

        updated_credential = replace(
            credential,
            password_hash=self._password_hash.hash(new_password),
            password_changed_at=current_time,
            must_change_password=False,
        )
        self._credentials.update_password_state(updated_credential)

        new_token = token_urlsafe(32)
        rotated_session = self._sessions.rotate_if_active(
            auth_session.id,
            auth_session.token_hash,
            self.hash_token(new_token),
            current_time,
        )
        if rotated_session is None:
            raise InvalidSessionError("Session is invalid")

        for other_session in self._sessions.list_for_user(user.id):
            if other_session.id == auth_session.id:
                continue
            if self._sessions.revoke_if_active(other_session.id, current_time):
                self._audit_session_revoked(user, other_session.id, user.id, current_time)

        self._audit.add(
            PlatformAuditEvent(
                id=PlatformAuditEventId(uuid4()),
                organization_id=user.organization_id,
                actor_user_id=user.id,
                target_user_id=user.id,
                target_session_id=auth_session.id,
                event_type="auth.password_changed",
                occurred_at=current_time,
            )
        )
        return PasswordChangeResult(token=new_token, auth_session=rotated_session, user=user)

    def _audit_login_failed(
        self,
        credential: LocalCredential | None,
        login_name: str,
        occurred_at: datetime,
    ) -> None:
        self._audit.add(
            PlatformAuditEvent(
                id=PlatformAuditEventId(uuid4()),
                organization_id=(credential.organization_id if credential is not None else None),
                target_user_id=credential.user_id if credential is not None else None,
                event_type="auth.login_failed",
                occurred_at=occurred_at,
                metadata={"login_name": login_name},
            )
        )

    def _audit_session_revoked(
        self,
        user: User,
        session_id: AuthSessionId,
        actor_user_id: UserId,
        occurred_at: datetime,
    ) -> None:
        self._audit.add(
            PlatformAuditEvent(
                id=PlatformAuditEventId(uuid4()),
                organization_id=user.organization_id,
                actor_user_id=actor_user_id,
                target_user_id=user.id,
                target_session_id=session_id,
                event_type="auth.session_revoked",
                occurred_at=occurred_at,
            )
        )

    @staticmethod
    def hash_token(token: str) -> str:
        return sha256(token.encode("utf-8")).hexdigest()
