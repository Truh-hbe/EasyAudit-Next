from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from uuid import uuid4

from pwdlib import PasswordHash

from easyaudit_next.platform.domain.ids import AuthSessionId, PlatformAuditEventId, UserId
from easyaudit_next.platform.domain.models import AuthSession, PlatformAuditEvent, User
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


@dataclass(frozen=True, slots=True)
class LoginResult:
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
        password_hash: PasswordHash | None = None,
    ) -> None:
        self._credentials = credentials
        self._sessions = sessions
        self._users = users
        self._audit = audit
        self._session_ttl = session_ttl
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
        credential = self._credentials.get_by_login_name(normalized_login)
        password_matches = self._password_hash.verify(
            password,
            credential.password_hash if credential is not None else self._dummy_hash,
        )
        user = self._users.get(credential.user_id) if credential is not None else None
        if credential is None or not password_matches or user is None or not user.is_active:
            self._audit.add(
                PlatformAuditEvent(
                    id=PlatformAuditEventId(uuid4()),
                    organization_id=credential.organization_id if credential is not None else None,
                    target_user_id=credential.user_id if credential is not None else None,
                    event_type="auth.login_failed",
                    occurred_at=current_time,
                    metadata={"login_name": normalized_login},
                )
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
        touched = replace(auth_session, last_seen_at=current_time)
        self._sessions.update(touched)
        return touched, user

    def logout(self, auth_session: AuthSession, user: User, *, now: datetime | None = None) -> None:
        current_time = now or datetime.now(UTC)
        if auth_session.revoked_at is None:
            self._sessions.update(replace(auth_session, revoked_at=current_time))
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
            if auth_session.revoked_at is None:
                self._sessions.update(replace(auth_session, revoked_at=current_time))
                self._audit.add(
                    PlatformAuditEvent(
                        id=PlatformAuditEventId(uuid4()),
                        organization_id=user.organization_id,
                        actor_user_id=actor_user_id,
                        target_user_id=user_id,
                        target_session_id=auth_session.id,
                        event_type="auth.session_revoked",
                        occurred_at=current_time,
                    )
                )

    @staticmethod
    def hash_token(token: str) -> str:
        return sha256(token.encode("utf-8")).hexdigest()
