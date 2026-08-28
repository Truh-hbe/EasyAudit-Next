from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pwdlib import PasswordHash

from easyaudit_next.platform.application.authentication import (
    AuthenticationService,
    InvalidCredentialsError,
    InvalidSessionError,
)
from easyaudit_next.platform.domain.ids import AuthSessionId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import (
    AuthSession,
    LocalCredential,
    PlatformAuditEvent,
    PlatformRole,
    User,
)

NOW = datetime(2026, 8, 21, tzinfo=UTC)


class CredentialRepository:
    def __init__(self, credential: LocalCredential | None) -> None:
        self.credential = credential

    def add(self, credential: LocalCredential) -> None:
        self.credential = credential

    def get_by_login_name(self, login_name: str) -> LocalCredential | None:
        if self.credential is not None and self.credential.login_name == login_name:
            return self.credential
        return None

    def get_by_user_id(self, user_id: UserId) -> LocalCredential | None:
        if self.credential is not None and self.credential.user_id == user_id:
            return self.credential
        return None

    def lock_by_login_name(self, login_name: str) -> LocalCredential | None:
        return self.get_by_login_name(login_name)

    def lock_by_user_id(self, user_id: UserId) -> LocalCredential | None:
        return self.get_by_user_id(user_id)

    def update_password_state(self, credential: LocalCredential) -> None:
        self.credential = credential


class SessionRepository:
    def __init__(self) -> None:
        self.items: dict[AuthSessionId, AuthSession] = {}

    def add(self, auth_session: AuthSession) -> None:
        self.items[auth_session.id] = auth_session

    def get_by_token_hash(self, token_hash: str) -> AuthSession | None:
        return next((item for item in self.items.values() if item.token_hash == token_hash), None)

    def get(self, session_id: AuthSessionId) -> AuthSession | None:
        return self.items.get(session_id)

    def list_for_user(self, user_id: UserId) -> tuple[AuthSession, ...]:
        return tuple(item for item in self.items.values() if item.user_id == user_id)

    def touch_if_active(
        self,
        session_id: AuthSessionId,
        expected_token_hash: str,
        touched_at: datetime,
    ) -> AuthSession | None:
        current = self.items.get(session_id)
        if (
            current is None
            or current.token_hash != expected_token_hash
            or current.revoked_at is not None
            or current.expires_at <= touched_at
        ):
            return None
        touched = replace(current, last_seen_at=touched_at)
        self.items[session_id] = touched
        return touched

    def revoke_if_active(self, session_id: AuthSessionId, revoked_at: datetime) -> bool:
        current = self.items.get(session_id)
        if (
            current is None
            or current.revoked_at is not None
            or current.expires_at <= revoked_at
        ):
            return False
        self.items[session_id] = replace(current, revoked_at=revoked_at)
        return True

    def rotate_if_active(
        self,
        session_id: AuthSessionId,
        expected_token_hash: str,
        new_token_hash: str,
        rotated_at: datetime,
    ) -> AuthSession | None:
        current = self.items.get(session_id)
        if (
            current is None
            or current.token_hash != expected_token_hash
            or current.revoked_at is not None
            or current.expires_at <= rotated_at
        ):
            return None
        rotated = replace(
            current,
            token_hash=new_token_hash,
            last_seen_at=rotated_at,
        )
        self.items[session_id] = rotated
        return rotated


class UserRepository:
    def __init__(self, user: User) -> None:
        self.user = user

    def add(self, user: User) -> None:
        self.user = user

    def get(self, user_id: UserId) -> User | None:
        return self.user if self.user.id == user_id else None

    def update(self, user: User) -> None:
        self.user = user

    def list_for_organization(self, organization_id: OrganizationId) -> tuple[User, ...]:
        return (self.user,) if self.user.organization_id == organization_id else ()

    def count_active_system_admins(self, organization_id: OrganizationId) -> int:
        return int(
            self.user.organization_id == organization_id
            and self.user.is_active
            and self.user.platform_role is PlatformRole.SYSTEM_ADMIN
        )


class AuditRepository:
    def __init__(self) -> None:
        self.events: list[PlatformAuditEvent] = []

    def add(self, event: PlatformAuditEvent) -> None:
        self.events.append(event)


def make_service() -> tuple[
    AuthenticationService, SessionRepository, UserRepository, AuditRepository
]:
    organization_id = OrganizationId(uuid4())
    user = User(
        id=UserId(uuid4()),
        organization_id=organization_id,
        display_name="Admin",
        platform_role=PlatformRole.SYSTEM_ADMIN,
    )
    password_hash = PasswordHash.recommended()
    credential = LocalCredential(
        user_id=user.id,
        organization_id=organization_id,
        login_name="admin",
        password_hash=password_hash.hash("correct-horse-battery"),
        password_changed_at=NOW,
    )
    sessions = SessionRepository()
    users = UserRepository(user)
    audit = AuditRepository()
    return (
        AuthenticationService(
            CredentialRepository(credential),
            sessions,
            users,
            audit,
            password_hash=password_hash,
        ),
        sessions,
        users,
        audit,
    )


def test_login_persists_only_token_hash() -> None:
    service, sessions, _, audit = make_service()
    result = service.login("ADMIN", "correct-horse-battery", now=NOW)

    stored = sessions.get(result.auth_session.id)
    assert stored is not None
    assert result.token != stored.token_hash
    assert stored.token_hash == service.hash_token(result.token)
    assert len(stored.token_hash) == 64
    assert audit.events[-1].event_type == "auth.login_succeeded"


def test_logout_immediately_invalidates_session() -> None:
    service, _, _, _ = make_service()
    result = service.login("admin", "correct-horse-battery", now=NOW)
    service.logout(result.auth_session, result.user, now=NOW)

    with pytest.raises(InvalidSessionError):
        service.authenticate(result.token, now=NOW)


def test_disabling_user_invalidates_existing_session() -> None:
    service, _, users, _ = make_service()
    result = service.login("admin", "correct-horse-battery", now=NOW)
    users.update(replace(result.user, is_active=False))

    with pytest.raises(InvalidSessionError):
        service.authenticate(result.token, now=NOW)


def test_failed_login_is_generic_and_audited() -> None:
    service, _, _, audit = make_service()

    with pytest.raises(InvalidCredentialsError, match="Invalid login name or password"):
        service.login("admin", "wrong-password", now=NOW)

    assert audit.events[-1].event_type == "auth.login_failed"
