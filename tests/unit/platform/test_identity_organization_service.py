from uuid import uuid4

import pytest

from easyaudit_next.platform.application.services import (
    DepartmentCycleError,
    IdentityOrganizationService,
    OrganizationBoundaryError,
)
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import Department, Organization, PlatformRole, User


class FakeOrganizationRepository:
    def __init__(self) -> None:
        self.items: dict[OrganizationId, Organization] = {}

    def add(self, organization: Organization) -> None:
        self.items[organization.id] = organization

    def get(self, organization_id: OrganizationId) -> Organization | None:
        return self.items.get(organization_id)

    def list_all(self) -> tuple[Organization, ...]:
        return tuple(self.items.values())


class FakeDepartmentRepository:
    def __init__(self) -> None:
        self.items: dict[DepartmentId, Department] = {}

    def add(self, department: Department) -> None:
        self.items[department.id] = department

    def get(self, department_id: DepartmentId) -> Department | None:
        return self.items.get(department_id)

    def update(self, department: Department) -> None:
        self.items[department.id] = department

    def list_for_organization(self, organization_id: OrganizationId) -> tuple[Department, ...]:
        return tuple(
            item for item in self.items.values() if item.organization_id == organization_id
        )


class FakeUserRepository:
    def __init__(self) -> None:
        self.items: dict[UserId, User] = {}

    def add(self, user: User) -> None:
        self.items[user.id] = user

    def get(self, user_id: UserId) -> User | None:
        return self.items.get(user_id)

    def update(self, user: User) -> None:
        self.items[user.id] = user

    def list_for_organization(self, organization_id: OrganizationId) -> tuple[User, ...]:
        return tuple(
            item for item in self.items.values() if item.organization_id == organization_id
        )


def make_service() -> IdentityOrganizationService:
    return IdentityOrganizationService(
        FakeOrganizationRepository(),
        FakeDepartmentRepository(),
        FakeUserRepository(),
    )


def test_service_generates_uuid4_ids_and_builds_primary_department() -> None:
    service = make_service()

    organization = service.create_organization("Example Manufacturing")
    department = service.create_department(organization.id, "Quality")
    user = service.create_user(
        organization.id,
        "Zhang San",
        platform_role=PlatformRole.ORDINARY_USER,
        primary_department_id=department.id,
    )

    assert organization.id.version == 4
    assert department.id.version == 4
    assert user.id.version == 4
    assert user.primary_department_id == department.id


def test_service_rejects_cross_organization_department_assignment() -> None:
    service = make_service()
    organization_a = service.create_organization("Organization A")
    organization_b = service.create_organization("Organization B")
    department_b = service.create_department(organization_b.id, "Department B")

    with pytest.raises(OrganizationBoundaryError):
        service.create_user(
            organization_a.id,
            "Cross-boundary user",
            primary_department_id=department_b.id,
        )


def test_service_rejects_indirect_department_cycle() -> None:
    service = make_service()
    organization = service.create_organization("Organization")
    root = service.create_department(organization.id, "Root")
    child = service.create_department(organization.id, "Child", parent_id=root.id)
    grandchild = service.create_department(organization.id, "Grandchild", parent_id=child.id)

    with pytest.raises(DepartmentCycleError):
        service.move_department(root.id, grandchild.id)


def test_domain_rejects_blank_names_and_self_parent() -> None:
    organization_id = OrganizationId(uuid4())
    department_id = DepartmentId(uuid4())

    with pytest.raises(ValueError, match="must not be blank"):
        Organization(id=organization_id, name="  ")
    with pytest.raises(ValueError, match="own parent"):
        Department(
            id=department_id,
            organization_id=organization_id,
            name="Quality",
            parent_id=department_id,
        )
