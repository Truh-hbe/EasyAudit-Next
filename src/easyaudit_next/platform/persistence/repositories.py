from sqlalchemy.orm import Session

from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import Department, Organization, PlatformRole, User
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
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
