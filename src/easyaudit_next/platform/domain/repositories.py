from datetime import datetime
from typing import Protocol

from easyaudit_next.platform.domain.ids import AuthSessionId, DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import (
    AuthSession,
    Department,
    LocalCredential,
    Organization,
    PlatformAuditEvent,
    User,
)


class OrganizationRepository(Protocol):
    def add(self, organization: Organization) -> None: ...

    def get(self, organization_id: OrganizationId) -> Organization | None: ...

    def lock_for_update(self, organization_id: OrganizationId) -> None: ...

    def list_all(self) -> tuple[Organization, ...]: ...


class DepartmentRepository(Protocol):
    def add(self, department: Department) -> None: ...

    def get(self, department_id: DepartmentId) -> Department | None: ...

    def update(self, department: Department) -> None: ...

    def list_for_organization(self, organization_id: OrganizationId) -> tuple[Department, ...]: ...


class UserRepository(Protocol):
    def add(self, user: User) -> None: ...

    def get(self, user_id: UserId) -> User | None: ...

    def update(self, user: User) -> None: ...

    def list_for_organization(self, organization_id: OrganizationId) -> tuple[User, ...]: ...

    def lock_users_for_update(
        self,
        organization_id: OrganizationId,
        user_ids: tuple[UserId, ...],
    ) -> tuple[User, ...]: ...

    def count_active_system_admins(self, organization_id: OrganizationId) -> int: ...


class LocalCredentialRepository(Protocol):
    def add(self, credential: LocalCredential) -> None: ...

    def get_by_login_name(self, login_name: str) -> LocalCredential | None: ...

    def get_by_user_id(self, user_id: UserId) -> LocalCredential | None: ...

    def lock_by_login_name(self, login_name: str) -> LocalCredential | None: ...

    def lock_by_user_id(self, user_id: UserId) -> LocalCredential | None: ...

    def update_password_state(self, credential: LocalCredential) -> None: ...


class AuthSessionRepository(Protocol):
    def add(self, auth_session: AuthSession) -> None: ...

    def get_by_token_hash(self, token_hash: str) -> AuthSession | None: ...

    def get(self, session_id: AuthSessionId) -> AuthSession | None: ...

    def list_for_user(self, user_id: UserId) -> tuple[AuthSession, ...]: ...

    def touch_if_active(
        self,
        session_id: AuthSessionId,
        expected_token_hash: str,
        touched_at: datetime,
    ) -> AuthSession | None: ...

    def revoke_if_active(self, session_id: AuthSessionId, revoked_at: datetime) -> bool: ...

    def rotate_if_active(
        self,
        session_id: AuthSessionId,
        expected_token_hash: str,
        new_token_hash: str,
        rotated_at: datetime,
    ) -> AuthSession | None: ...


class PlatformAuditRepository(Protocol):
    def add(self, event: PlatformAuditEvent) -> None: ...
