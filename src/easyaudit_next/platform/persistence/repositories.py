from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from easyaudit_next.platform.domain.ids import (
    AuthSessionId,
    DepartmentId,
    OrganizationId,
    UserId,
)
from easyaudit_next.platform.domain.models import (
    AuthSession,
    Department,
    LocalCredential,
    Organization,
    PlatformAuditEvent,
    PlatformRole,
    User,
)
from easyaudit_next.platform.persistence.models import (
    AuthSessionRecord,
    DepartmentRecord,
    LocalCredentialRecord,
    OrganizationRecord,
    PlatformAuditEventRecord,
    UserRecord,
)


class SqlAlchemyOrganizationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, organization: Organization) -> None:
        self._session.add(
            OrganizationRecord(
                id=organization.id,
                name=organization.name,
                is_active=organization.is_active,
            )
        )
        self._session.flush()

    def get(self, organization_id: OrganizationId) -> Organization | None:
        record = self._session.get(OrganizationRecord, organization_id)
        if record is None:
            return None
        return Organization(
            id=OrganizationId(record.id),
            name=record.name,
            is_active=record.is_active,
        )

    def lock_for_update(self, organization_id: OrganizationId) -> None:
        locked_id = self._session.scalar(
            select(OrganizationRecord.id)
            .where(OrganizationRecord.id == organization_id)
            .with_for_update()
        )
        if locked_id is None:
            raise LookupError(f"Organization {organization_id} does not exist")

    def list_all(self) -> tuple[Organization, ...]:
        records = self._session.scalars(
            select(OrganizationRecord).order_by(OrganizationRecord.name)
        )
        return tuple(
            Organization(
                id=OrganizationId(record.id),
                name=record.name,
                is_active=record.is_active,
            )
            for record in records
        )


class SqlAlchemyDepartmentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, department: Department) -> None:
        self._session.add(
            DepartmentRecord(
                id=department.id,
                organization_id=department.organization_id,
                parent_id=department.parent_id,
                name=department.name,
                is_active=department.is_active,
            )
        )
        self._session.flush()

    def get(self, department_id: DepartmentId) -> Department | None:
        record = self._session.get(DepartmentRecord, department_id)
        if record is None:
            return None
        return self._to_domain(record)

    def update(self, department: Department) -> None:
        record = self._session.get(DepartmentRecord, department.id)
        if record is None:
            raise LookupError(f"Department {department.id} does not exist")
        record.organization_id = department.organization_id
        record.parent_id = department.parent_id
        record.name = department.name
        record.is_active = department.is_active
        self._session.flush()

    def list_for_organization(self, organization_id: OrganizationId) -> tuple[Department, ...]:
        records = self._session.scalars(
            select(DepartmentRecord)
            .where(DepartmentRecord.organization_id == organization_id)
            .order_by(DepartmentRecord.name)
        )
        return tuple(self._to_domain(record) for record in records)

    @staticmethod
    def _to_domain(record: DepartmentRecord) -> Department:
        parent_id = DepartmentId(record.parent_id) if record.parent_id is not None else None
        return Department(
            id=DepartmentId(record.id),
            organization_id=OrganizationId(record.organization_id),
            name=record.name,
            parent_id=parent_id,
            is_active=record.is_active,
        )


class SqlAlchemyUserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, user: User) -> None:
        self._session.add(
            UserRecord(
                id=user.id,
                organization_id=user.organization_id,
                primary_department_id=user.primary_department_id,
                display_name=user.display_name,
                platform_role=user.platform_role.value,
                is_active=user.is_active,
            )
        )
        self._session.flush()

    def get(self, user_id: UserId) -> User | None:
        record = self._session.get(UserRecord, user_id)
        if record is None:
            return None
        return self._to_domain(record)

    def update(self, user: User) -> None:
        record = self._session.get(UserRecord, user.id)
        if record is None:
            raise LookupError(f"User {user.id} does not exist")
        record.organization_id = user.organization_id
        record.primary_department_id = user.primary_department_id
        record.display_name = user.display_name
        record.platform_role = user.platform_role.value
        record.is_active = user.is_active
        self._session.flush()

    def list_for_organization(self, organization_id: OrganizationId) -> tuple[User, ...]:
        records = self._session.scalars(
            select(UserRecord)
            .where(UserRecord.organization_id == organization_id)
            .order_by(UserRecord.display_name)
        )
        return tuple(self._to_domain(record) for record in records)

    def lock_users_for_update(
        self,
        organization_id: OrganizationId,
        user_ids: tuple[UserId, ...],
    ) -> tuple[User, ...]:
        if not user_ids:
            return ()
        records = self._session.scalars(
            select(UserRecord)
            .where(
                UserRecord.organization_id == organization_id,
                UserRecord.id.in_(user_ids),
            )
            .order_by(UserRecord.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return tuple(self._to_domain(record) for record in records)

    def count_active_system_admins(self, organization_id: OrganizationId) -> int:
        count = self._session.scalar(
            select(func.count())
            .select_from(UserRecord)
            .where(
                UserRecord.organization_id == organization_id,
                UserRecord.is_active.is_(True),
                UserRecord.platform_role == PlatformRole.SYSTEM_ADMIN.value,
            )
        )
        return int(count or 0)

    @staticmethod
    def _to_domain(record: UserRecord) -> User:
        department_id = (
            DepartmentId(record.primary_department_id)
            if record.primary_department_id is not None
            else None
        )
        return User(
            id=UserId(record.id),
            organization_id=OrganizationId(record.organization_id),
            display_name=record.display_name,
            platform_role=PlatformRole(record.platform_role),
            primary_department_id=department_id,
            is_active=record.is_active,
        )


class SqlAlchemyLocalCredentialRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, credential: LocalCredential) -> None:
        self._session.add(
            LocalCredentialRecord(
                user_id=credential.user_id,
                organization_id=credential.organization_id,
                login_name=credential.login_name,
                password_hash=credential.password_hash,
                password_changed_at=credential.password_changed_at,
                must_change_password=credential.must_change_password,
            )
        )
        self._session.flush()

    def get_by_login_name(self, login_name: str) -> LocalCredential | None:
        record = self._session.scalar(
            select(LocalCredentialRecord).where(
                LocalCredentialRecord.login_name == login_name.strip().lower()
            )
        )
        return self._to_domain(record) if record is not None else None

    def get_by_user_id(self, user_id: UserId) -> LocalCredential | None:
        record = self._session.scalar(
            select(LocalCredentialRecord).where(LocalCredentialRecord.user_id == user_id)
        )
        return self._to_domain(record) if record is not None else None

    def lock_by_login_name(self, login_name: str) -> LocalCredential | None:
        record = self._session.scalar(
            select(LocalCredentialRecord)
            .where(LocalCredentialRecord.login_name == login_name.strip().lower())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._to_domain(record) if record is not None else None

    def lock_by_user_id(self, user_id: UserId) -> LocalCredential | None:
        record = self._session.scalar(
            select(LocalCredentialRecord)
            .where(LocalCredentialRecord.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._to_domain(record) if record is not None else None

    def update_password_state(self, credential: LocalCredential) -> None:
        record = self._session.get(
            LocalCredentialRecord,
            credential.user_id,
            populate_existing=True,
        )
        if record is None or record.organization_id != credential.organization_id:
            raise LookupError(f"LocalCredential for user {credential.user_id} does not exist")
        record.password_hash = credential.password_hash
        record.password_changed_at = credential.password_changed_at
        record.must_change_password = credential.must_change_password
        self._session.flush()

    @staticmethod
    def _to_domain(record: LocalCredentialRecord) -> LocalCredential:
        return LocalCredential(
            user_id=UserId(record.user_id),
            organization_id=OrganizationId(record.organization_id),
            login_name=record.login_name,
            password_hash=record.password_hash,
            password_changed_at=record.password_changed_at,
            must_change_password=record.must_change_password,
        )


class SqlAlchemyAuthSessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, auth_session: AuthSession) -> None:
        self._session.add(self._to_record(auth_session))
        self._session.flush()

    def get_by_token_hash(self, token_hash: str) -> AuthSession | None:
        record = self._session.scalar(
            select(AuthSessionRecord)
            .where(AuthSessionRecord.token_hash == token_hash)
            .execution_options(populate_existing=True)
        )
        return self._to_domain(record) if record is not None else None

    def get(self, session_id: AuthSessionId) -> AuthSession | None:
        record = self._session.scalar(
            select(AuthSessionRecord)
            .where(AuthSessionRecord.id == session_id)
            .execution_options(populate_existing=True)
        )
        return self._to_domain(record) if record is not None else None

    def list_for_user(self, user_id: UserId) -> tuple[AuthSession, ...]:
        records = self._session.scalars(
            select(AuthSessionRecord)
            .where(AuthSessionRecord.user_id == user_id)
            .order_by(AuthSessionRecord.created_at.desc())
            .execution_options(populate_existing=True)
        )
        return tuple(self._to_domain(record) for record in records)

    def touch_if_active(
        self,
        session_id: AuthSessionId,
        expected_token_hash: str,
        touched_at: datetime,
        *,
        min_interval: timedelta = timedelta(0),
    ) -> AuthSession | None:
        """Record activity; None when nothing was written (inactive, or touched within
        `min_interval` already: then no UPDATE takes place at all)."""
        result = self._session.execute(
            sa_update(AuthSessionRecord)
            .where(
                AuthSessionRecord.id == session_id,
                AuthSessionRecord.token_hash == expected_token_hash,
                AuthSessionRecord.revoked_at.is_(None),
                AuthSessionRecord.expires_at > touched_at,
                or_(
                    AuthSessionRecord.last_seen_at.is_(None),
                    AuthSessionRecord.last_seen_at < touched_at - min_interval,
                ),
            )
            .values(last_seen_at=touched_at)
            .returning(AuthSessionRecord.id),
            execution_options={"synchronize_session": False},
        )
        if result.scalar_one_or_none() is None:
            return None
        return self.get(session_id)

    def revoke_if_active(self, session_id: AuthSessionId, revoked_at: datetime) -> bool:
        result = self._session.execute(
            sa_update(AuthSessionRecord)
            .where(
                AuthSessionRecord.id == session_id,
                AuthSessionRecord.revoked_at.is_(None),
                AuthSessionRecord.expires_at > revoked_at,
            )
            .values(revoked_at=revoked_at)
            .returning(AuthSessionRecord.id),
            execution_options={"synchronize_session": False},
        )
        return result.scalar_one_or_none() is not None

    def rotate_if_active(
        self,
        session_id: AuthSessionId,
        expected_token_hash: str,
        new_token_hash: str,
        rotated_at: datetime,
    ) -> AuthSession | None:
        result = self._session.execute(
            sa_update(AuthSessionRecord)
            .where(
                AuthSessionRecord.id == session_id,
                AuthSessionRecord.token_hash == expected_token_hash,
                AuthSessionRecord.revoked_at.is_(None),
                AuthSessionRecord.expires_at > rotated_at,
            )
            .values(token_hash=new_token_hash, last_seen_at=rotated_at)
            .returning(AuthSessionRecord.id),
            execution_options={"synchronize_session": False},
        )
        if result.scalar_one_or_none() is None:
            return None
        return self.get(session_id)

    @staticmethod
    def _to_record(auth_session: AuthSession) -> AuthSessionRecord:
        return AuthSessionRecord(
            id=auth_session.id,
            organization_id=auth_session.organization_id,
            user_id=auth_session.user_id,
            token_hash=auth_session.token_hash,
            expires_at=auth_session.expires_at,
            revoked_at=auth_session.revoked_at,
            last_seen_at=auth_session.last_seen_at,
            created_at=auth_session.created_at,
        )

    @staticmethod
    def _to_domain(record: AuthSessionRecord) -> AuthSession:
        return AuthSession(
            id=AuthSessionId(record.id),
            organization_id=OrganizationId(record.organization_id),
            user_id=UserId(record.user_id),
            token_hash=record.token_hash,
            expires_at=record.expires_at,
            revoked_at=record.revoked_at,
            last_seen_at=record.last_seen_at,
            created_at=record.created_at,
        )


class SqlAlchemyPlatformAuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: PlatformAuditEvent) -> None:
        self._session.add(
            PlatformAuditEventRecord(
                id=event.id,
                organization_id=event.organization_id,
                actor_user_id=event.actor_user_id,
                target_user_id=event.target_user_id,
                target_department_id=event.target_department_id,
                target_session_id=event.target_session_id,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                metadata_json=dict(event.metadata),
            )
        )
        self._session.flush()
