from dataclasses import replace
from uuid import UUID, uuid4

from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import Department, Organization, PlatformRole, User
from easyaudit_next.platform.domain.repositories import (
    DepartmentRepository,
    OrganizationRepository,
    UserRepository,
)


class PlatformEntityNotFoundError(LookupError):
    """A referenced platform entity does not exist."""


class OrganizationBoundaryError(ValueError):
    """A relationship attempts to cross an organization boundary."""


class DepartmentCycleError(ValueError):
    """A department parent change would create a cycle."""


class IdentityOrganizationService:
    """Coordinates identity and organization writes within the caller's transaction."""

    def __init__(
        self,
        organizations: OrganizationRepository,
        departments: DepartmentRepository,
        users: UserRepository,
    ) -> None:
        self._organizations = organizations
        self._departments = departments
        self._users = users

    def create_organization(
        self,
        name: str,
        *,
        organization_id: OrganizationId | None = None,
    ) -> Organization:
        organization = Organization(
            id=organization_id or OrganizationId(uuid4()),
            name=name,
        )
        self._organizations.add(organization)
        return organization

    def create_department(
        self,
        organization_id: OrganizationId,
        name: str,
        *,
        parent_id: DepartmentId | None = None,
        department_id: DepartmentId | None = None,
    ) -> Department:
        self._require_organization(organization_id)
        if parent_id is not None:
            self._require_department_in_organization(parent_id, organization_id)
        department = Department(
            id=department_id or DepartmentId(uuid4()),
            organization_id=organization_id,
            name=name,
            parent_id=parent_id,
        )
        self._departments.add(department)
        return department

    def move_department(
        self,
        department_id: DepartmentId,
        parent_id: DepartmentId | None,
    ) -> Department:
        # Serialize hierarchy changes per organization: the ancestor check and the UPDATE must
        # see each other's committed moves. The first read only discovers the organization;
        # everything decisive is re-read after the lock with `get_current`.
        organization_id = self._require_department(department_id).organization_id
        self._organizations.lock_for_update(organization_id)
        department = self._require_department(department_id, current=True)
        if parent_id is not None:
            self._require_department_in_organization(
                parent_id, department.organization_id, current=True
            )
            self._assert_no_department_cycle(department_id, parent_id)
        updated = replace(department, parent_id=parent_id)
        self._departments.update(updated)
        return updated

    def create_user(
        self,
        organization_id: OrganizationId,
        display_name: str,
        *,
        platform_role: PlatformRole = PlatformRole.ORDINARY_USER,
        primary_department_id: DepartmentId | None = None,
        user_id: UserId | None = None,
    ) -> User:
        self._require_organization(organization_id)
        if primary_department_id is not None:
            self._require_department_in_organization(primary_department_id, organization_id)
        user = User(
            id=user_id or UserId(uuid4()),
            organization_id=organization_id,
            display_name=display_name,
            platform_role=platform_role,
            primary_department_id=primary_department_id,
        )
        self._users.add(user)
        return user

    def assign_primary_department(
        self,
        user_id: UserId,
        department_id: DepartmentId | None,
    ) -> User:
        user = self._require_user(user_id)
        if department_id is not None:
            self._require_department_in_organization(department_id, user.organization_id)
        updated = replace(user, primary_department_id=department_id)
        self._users.update(updated)
        return updated

    def _require_organization(self, organization_id: OrganizationId) -> Organization:
        organization = self._organizations.get(organization_id)
        if organization is None:
            raise PlatformEntityNotFoundError(f"Organization {organization_id} does not exist")
        return organization

    def _require_department(
        self, department_id: DepartmentId, *, current: bool = False
    ) -> Department:
        department = (
            self._departments.get_current(department_id)
            if current
            else self._departments.get(department_id)
        )
        if department is None:
            raise PlatformEntityNotFoundError(f"Department {department_id} does not exist")
        return department

    def _require_department_in_organization(
        self,
        department_id: DepartmentId,
        organization_id: OrganizationId,
        *,
        current: bool = False,
    ) -> Department:
        department = self._require_department(department_id, current=current)
        if department.organization_id != organization_id:
            raise OrganizationBoundaryError(
                f"Department {department_id} does not belong to organization {organization_id}"
            )
        return department

    def _require_user(self, user_id: UserId) -> User:
        user = self._users.get(user_id)
        if user is None:
            raise PlatformEntityNotFoundError(f"User {user_id} does not exist")
        return user

    def _assert_no_department_cycle(
        self,
        department_id: DepartmentId,
        proposed_parent_id: DepartmentId,
    ) -> None:
        current_id: DepartmentId | None = proposed_parent_id
        visited: set[UUID] = set()
        while current_id is not None:
            if current_id == department_id:
                raise DepartmentCycleError("Department parent would create a cycle")
            if current_id in visited:
                raise DepartmentCycleError("Existing department hierarchy contains a cycle")
            visited.add(current_id)
            current_id = self._require_department(current_id, current=True).parent_id
