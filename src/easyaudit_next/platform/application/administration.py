from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from pwdlib import PasswordHash

from easyaudit_next.platform.application.authentication import (
    AuthenticationService,
    LocalCredentialUnavailableError,
)
from easyaudit_next.platform.application.password_policy import validate_local_password
from easyaudit_next.platform.application.services import IdentityOrganizationService
from easyaudit_next.platform.domain.ids import DepartmentId, PlatformAuditEventId, UserId
from easyaudit_next.platform.domain.models import (
    Department,
    LocalCredential,
    PlatformAuditEvent,
    PlatformRole,
    User,
)
from easyaudit_next.platform.domain.repositories import (
    DepartmentRepository,
    LocalCredentialRepository,
    OrganizationRepository,
    PlatformAuditRepository,
    UserRepository,
)


class LastSystemAdminError(ValueError):
    """The final active system administrator cannot be disabled or demoted."""


class PlatformAdministrationService:
    def __init__(
        self,
        identity: IdentityOrganizationService,
        organizations: OrganizationRepository,
        departments: DepartmentRepository,
        users: UserRepository,
        credentials: LocalCredentialRepository,
        sessions: AuthenticationService,
        audit: PlatformAuditRepository,
        *,
        password_hash: PasswordHash | None = None,
    ) -> None:
        self._identity = identity
        self._organizations = organizations
        self._departments = departments
        self._users = users
        self._credentials = credentials
        self._sessions = sessions
        self._audit = audit
        self._password_hash = password_hash or PasswordHash.recommended()

    def create_local_user(
        self,
        actor: User,
        display_name: str,
        login_name: str,
        password: str,
        *,
        primary_department_id: DepartmentId | None = None,
        platform_role: PlatformRole = PlatformRole.ORDINARY_USER,
        must_change_password: bool = True,
        now: datetime | None = None,
    ) -> User:
        self._require_system_admin(actor)
        self._validate_password(password)
        current_time = now or datetime.now(UTC)
        user = self._identity.create_user(
            actor.organization_id,
            display_name,
            primary_department_id=primary_department_id,
            platform_role=platform_role,
        )
        self._credentials.add(
            LocalCredential(
                user_id=user.id,
                organization_id=user.organization_id,
                login_name=login_name.strip().lower(),
                password_hash=self._password_hash.hash(password),
                password_changed_at=current_time,
                must_change_password=must_change_password,
            )
        )
        self._audit.add(
            PlatformAuditEvent(
                id=PlatformAuditEventId(uuid4()),
                organization_id=user.organization_id,
                actor_user_id=actor.id,
                target_user_id=user.id,
                event_type="admin.user_created",
                occurred_at=current_time,
            )
        )
        return user

    def update_user(
        self,
        actor: User,
        user_id: UserId,
        *,
        display_name: str | None = None,
        primary_department_id: DepartmentId | None = None,
        set_primary_department: bool = False,
        platform_role: PlatformRole | None = None,
        is_active: bool | None = None,
        now: datetime | None = None,
    ) -> User:
        self._require_system_admin(actor)
        user = self._users.get(user_id)
        if user is None or user.organization_id != actor.organization_id:
            raise LookupError(f"User {user_id} does not exist")
        updated = replace(
            user,
            display_name=display_name if display_name is not None else user.display_name,
            primary_department_id=(
                primary_department_id if set_primary_department else user.primary_department_id
            ),
            platform_role=platform_role if platform_role is not None else user.platform_role,
            is_active=is_active if is_active is not None else user.is_active,
        )
        removes_active_admin = (
            user.is_active
            and user.platform_role is PlatformRole.SYSTEM_ADMIN
            and (not updated.is_active or updated.platform_role is not PlatformRole.SYSTEM_ADMIN)
        )
        if removes_active_admin:
            self._organizations.lock_for_update(user.organization_id)
            if self._users.count_active_system_admins(user.organization_id) <= 1:
                raise LastSystemAdminError("Cannot disable or demote the last active system_admin")
        if set_primary_department and primary_department_id is not None:
            department = self._departments.get(primary_department_id)
            if department is None or department.organization_id != actor.organization_id:
                raise ValueError("Primary department must belong to the actor's organization")
        self._users.update(updated)
        current_time = now or datetime.now(UTC)
        if user.is_active and not updated.is_active:
            self._sessions.revoke_user_sessions(
                user.id,
                actor_user_id=actor.id,
                now=current_time,
            )
        self._audit.add(
            PlatformAuditEvent(
                id=PlatformAuditEventId(uuid4()),
                organization_id=user.organization_id,
                actor_user_id=actor.id,
                target_user_id=user.id,
                event_type="admin.user_updated",
                occurred_at=current_time,
                metadata={"is_active": updated.is_active},
            )
        )
        return updated

    def reset_local_credential(
        self,
        actor: User,
        user_id: UserId,
        temporary_password: str,
        *,
        now: datetime | None = None,
    ) -> User:
        """Replace one local credential inside the request-owned transaction."""

        self._require_system_admin(actor)
        user = self._users.get(user_id)
        if user is None or user.organization_id != actor.organization_id:
            raise LookupError(f"User {user_id} does not exist")

        self._validate_password(temporary_password)
        current_time = now or datetime.now(UTC)
        # The credential row is the serialization point shared by login and the
        # self-service password-change flow. Hashing before the lock keeps the
        # lock hold time small; all credential-dependent mutation follows it.
        password_hash = self._password_hash.hash(temporary_password)
        credential = self._credentials.lock_by_user_id(user.id)
        if credential is None or credential.organization_id != user.organization_id:
            raise LocalCredentialUnavailableError("Local credential is unavailable")

        self._credentials.update_password_state(
            replace(
                credential,
                password_hash=password_hash,
                password_changed_at=current_time,
                must_change_password=True,
            )
        )
        self._sessions.revoke_user_sessions(
            user.id,
            actor_user_id=actor.id,
            now=current_time,
        )
        self._audit.add(
            PlatformAuditEvent(
                id=PlatformAuditEventId(uuid4()),
                organization_id=user.organization_id,
                actor_user_id=actor.id,
                target_user_id=user.id,
                event_type="admin.user_credential_reset",
                occurred_at=current_time,
            )
        )
        return user

    def create_department(
        self,
        actor: User,
        name: str,
        *,
        parent_id: DepartmentId | None = None,
        now: datetime | None = None,
    ) -> Department:
        self._require_system_admin(actor)
        department = self._identity.create_department(
            actor.organization_id,
            name,
            parent_id=parent_id,
        )
        self._audit_department(actor, department, "admin.department_created", now)
        return department

    def update_department(
        self,
        actor: User,
        department_id: DepartmentId,
        *,
        name: str | None = None,
        parent_id: DepartmentId | None = None,
        set_parent: bool = False,
        is_active: bool | None = None,
        now: datetime | None = None,
    ) -> Department:
        self._require_system_admin(actor)
        department = self._departments.get(department_id)
        if department is None or department.organization_id != actor.organization_id:
            raise LookupError(f"Department {department_id} does not exist")
        if set_parent:
            department = self._identity.move_department(department_id, parent_id)
        updated = replace(
            department,
            name=name if name is not None else department.name,
            is_active=is_active if is_active is not None else department.is_active,
        )
        self._departments.update(updated)
        self._audit_department(actor, updated, "admin.department_updated", now)
        return updated

    def _audit_department(
        self,
        actor: User,
        department: Department,
        event_type: str,
        now: datetime | None,
    ) -> None:
        self._audit.add(
            PlatformAuditEvent(
                id=PlatformAuditEventId(uuid4()),
                organization_id=actor.organization_id,
                actor_user_id=actor.id,
                target_department_id=department.id,
                event_type=event_type,
                occurred_at=now or datetime.now(UTC),
            )
        )

    @staticmethod
    def _require_system_admin(actor: User) -> None:
        if actor.platform_role is not PlatformRole.SYSTEM_ADMIN:
            raise PermissionError("system_admin platform role is required")

    @staticmethod
    def _validate_password(password: str) -> None:
        validate_local_password(password)
