from dataclasses import replace
from datetime import datetime

from easyaudit_next.platform.application.administration import PlatformAdministrationService
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import PlatformRole, User
from easyaudit_next.platform.domain.repositories import (
    OrganizationRepository,
    UserRepository,
)
from easyaudit_next.review_core.application.mutation_results import (
    CaseMemberAddedResult,
    CaseMemberRemovedResult,
)
from easyaudit_next.review_core.application.review_planning import (
    ReviewPlanningService,
    effective_case_manager_ids,
)
from easyaudit_next.review_core.domain.ids import ReviewCaseId, ReviewPlanId
from easyaudit_next.review_core.domain.models import (
    CaseMember,
    ReviewCase,
    ScenarioKey,
    ScenarioVersion,
)
from easyaudit_next.review_core.domain.repositories import ReviewCoreRepository
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry


class UserDeactivationConflictError(RuntimeError):
    """Deactivation would leave at least one Case without an effective manager."""


class CaseTeamUserCoordinator:
    """Serialize Case-team mutations and User deactivation at the Organization root."""

    def __init__(
        self,
        organizations: OrganizationRepository,
        review_repository: ReviewCoreRepository,
        users: UserRepository,
        registry: ScenarioRegistry,
        planning: ReviewPlanningService,
        administration: PlatformAdministrationService,
    ) -> None:
        self._organizations = organizations
        self._review_repository = review_repository
        self._users = users
        self._registry = registry
        self._planning = planning
        self._administration = administration

    def create_case(
        self,
        actor: User,
        scenario_key: ScenarioKey,
        scenario_version: ScenarioVersion,
        title: str,
        scenario_data: dict[str, object],
        *,
        plan_id: ReviewPlanId | None = None,
        planned_start_at: datetime | None = None,
        planned_end_at: datetime | None = None,
        occurred_at: datetime | None = None,
        new_case_id: ReviewCaseId | None = None,
    ) -> ReviewCase:
        fresh_actor = self._lock_actor(actor)
        return self._planning.create_case(
            fresh_actor,
            scenario_key,
            scenario_version,
            title,
            scenario_data,
            plan_id=plan_id,
            planned_start_at=planned_start_at,
            planned_end_at=planned_end_at,
            occurred_at=occurred_at,
            new_case_id=new_case_id,
        )

    def add_case_member_result(
        self,
        actor: User,
        case_id: ReviewCaseId,
        user_id: UserId,
        role_key: str,
        *,
        occurred_at: datetime | None = None,
    ) -> CaseMemberAddedResult:
        self._organizations.lock_for_update(actor.organization_id)
        locked_case = self._review_repository.lock_case_for_team_management(
            actor.organization_id,
            case_id,
        )
        if locked_case is None:
            raise LookupError("ReviewCase not found")
        locked_users = self._users.lock_users_for_update(
            actor.organization_id,
            tuple(sorted({actor.id, user_id}, key=str)),
        )
        fresh_actor = self._find_user(locked_users, actor.id)
        if fresh_actor is None:
            raise LookupError(f"User {actor.id} does not exist")
        return self._planning.add_case_member_result(
            fresh_actor,
            locked_case.id,
            user_id,
            role_key,
            occurred_at=occurred_at,
        )

    def remove_case_member_result(
        self,
        actor: User,
        case_id: ReviewCaseId,
        user_id: UserId,
        role_key: str,
        *,
        occurred_at: datetime | None = None,
    ) -> CaseMemberRemovedResult:
        self._organizations.lock_for_update(actor.organization_id)
        return self._planning.remove_case_member_result(
            actor,
            case_id,
            user_id,
            role_key,
            occurred_at=occurred_at,
        )

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
        if is_active is not False:
            return self._administration.update_user(
                actor,
                user_id,
                display_name=display_name,
                primary_department_id=primary_department_id,
                set_primary_department=set_primary_department,
                platform_role=platform_role,
                is_active=is_active,
                now=now,
            )

        if actor.platform_role is not PlatformRole.SYSTEM_ADMIN:
            raise PermissionError("system_admin platform role is required")
        self._organizations.lock_for_update(actor.organization_id)
        # Authorize against the current actor row before touching any target or Case fact, so a
        # concurrently demoted/deactivated admin gets 403 rather than a 404/409 that leaks state.
        # No User row lock here: that would precede the Case locks taken below.
        current_actor = self._users.get_current(actor.organization_id, actor.id)
        if current_actor is None:
            raise LookupError(f"User {actor.id} does not exist")
        if (
            not current_actor.is_active
            or current_actor.platform_role is not PlatformRole.SYSTEM_ADMIN
        ):
            raise PermissionError("system_admin platform role is required")
        target = self._users.get(user_id)
        if target is None or target.organization_id != actor.organization_id:
            raise LookupError(f"User {user_id} does not exist")
        if target.is_active:
            fresh_actor = self._ensure_cases_remain_managed(
                actor.organization_id,
                actor.id,
                target.id,
            )
        else:
            locked_users = self._users.lock_users_for_update(
                actor.organization_id,
                tuple(sorted({actor.id, target.id}, key=str)),
            )
            locked_actor = self._find_user(locked_users, actor.id)
            if locked_actor is None:
                raise LookupError(f"User {actor.id} does not exist")
            fresh_actor = locked_actor
        if fresh_actor.platform_role is not PlatformRole.SYSTEM_ADMIN:
            raise PermissionError("system_admin platform role is required")

        return self._administration.update_user(
            fresh_actor,
            user_id,
            display_name=display_name,
            primary_department_id=primary_department_id,
            set_primary_department=set_primary_department,
            platform_role=platform_role,
            is_active=is_active,
            now=now,
        )

    def _ensure_cases_remain_managed(
        self,
        organization_id: OrganizationId,
        actor_user_id: UserId,
        target_user_id: UserId,
    ) -> User:
        # The Organization lock is held before this enumeration. Every Case lock and
        # User lock below follows the documented Organization -> Case -> User order.
        affected_cases = self._review_repository.list_cases_for_member(
            organization_id,
            target_user_id,
        )
        locked_cases: list[ReviewCase] = []
        for review_case in sorted(affected_cases, key=lambda item: str(item.id)):
            locked_case = self._review_repository.lock_case_for_team_management(
                organization_id,
                review_case.id,
            )
            if locked_case is not None:
                locked_cases.append(locked_case)

        members_by_case: dict[ReviewCaseId, tuple[CaseMember, ...]] = {}
        member_user_ids: set[UserId] = set()
        for review_case in locked_cases:
            members = self._review_repository.list_case_members(organization_id, review_case.id)
            members_by_case[review_case.id] = members
            member_user_ids.update(member.user_id for member in members)
        member_user_ids.update({actor_user_id, target_user_id})
        locked_users = self._users.lock_users_for_update(
            organization_id,
            tuple(sorted(member_user_ids, key=str)),
        )
        deactivated_target = next(
            (user for user in locked_users if user.id == target_user_id),
            None,
        )
        if deactivated_target is None:
            raise LookupError(f"User {target_user_id} does not exist")
        fresh_actor = next(
            (user for user in locked_users if user.id == actor_user_id),
            None,
        )
        if fresh_actor is None:
            raise LookupError(f"User {actor_user_id} does not exist")
        deactivated_target = replace(deactivated_target, is_active=False)
        users_after = tuple(
            deactivated_target if user.id == target_user_id else user
            for user in locked_users
        )

        for review_case in locked_cases:
            policy = self._registry.get(review_case.scenario_key, review_case.scenario_version)
            if not effective_case_manager_ids(
                policy,
                members_by_case[review_case.id],
                users_after,
            ):
                raise UserDeactivationConflictError(
                    "Cannot deactivate User while a ReviewCase would have no effective manager"
                )
        return fresh_actor

    def _lock_actor(self, actor: User) -> User:
        self._organizations.lock_for_update(actor.organization_id)
        locked_users = self._users.lock_users_for_update(
            actor.organization_id,
            (actor.id,),
        )
        fresh_actor = self._find_user(locked_users, actor.id)
        if fresh_actor is None:
            raise LookupError(f"User {actor.id} does not exist")
        return fresh_actor

    @staticmethod
    def _find_user(users: tuple[User, ...], user_id: UserId) -> User | None:
        return next((user for user in users if user.id == user_id), None)
