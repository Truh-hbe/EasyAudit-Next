from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from easyaudit_next.platform.domain.ids import UserId
from easyaudit_next.platform.domain.models import User
from easyaudit_next.platform.domain.repositories import UserRepository
from easyaudit_next.review_core.application.authorization import build_authorization_context
from easyaudit_next.review_core.application.mutation_results import CaseMemberAddedResult
from easyaudit_next.review_core.domain.ids import (
    ActivityId,
    ReviewCaseId,
    ReviewPlanId,
)
from easyaudit_next.review_core.domain.models import (
    Activity,
    CaseMember,
    ReviewCase,
    ReviewCaseActivitySubject,
    ReviewCaseLifecycle,
    ReviewPlan,
    ScenarioKey,
    ScenarioVersion,
)
from easyaudit_next.review_core.domain.planning_policy import (
    CORE_REVIEW_PLANNING_AUTHORIZATION,
    PlanningAuthorizationContext,
    ReviewPlanningPermission,
)
from easyaudit_next.review_core.domain.repositories import (
    ReviewCoreRepository,
    ScenarioCatalogRepository,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActorKind,
    AuthorizationContext,
    PermissionSource,
    ReviewCaseTransitionContext,
    RoleGrant,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioPolicy, ScenarioRegistry

VIEW_CASE_PERMISSION = "view_case"
MANAGE_CASE_MEMBERS_PERMISSION = "manage_case_members"
TRANSITION_CASE_PERMISSION = "transition_case"


class ReviewAuthorizationError(PermissionError):
    """The authenticated user lacks the required business relationship."""


class ConcurrentCaseTransitionError(RuntimeError):
    """The persisted lifecycle no longer matches the workflow input."""


class ReviewPlanningService:
    """M2.2 use cases for ReviewPlan, ReviewCase, CaseMember, and Case transitions."""

    def __init__(
        self,
        repository: ReviewCoreRepository,
        scenario_catalog: ScenarioCatalogRepository,
        users: UserRepository,
        registry: ScenarioRegistry,
    ) -> None:
        self._repository = repository
        self._scenario_catalog = scenario_catalog
        self._users = users
        self._registry = registry

    def create_plan(
        self,
        actor: User,
        title: str,
        *,
        planned_start_at: datetime | None = None,
        planned_end_at: datetime | None = None,
    ) -> ReviewPlan:
        if not CORE_REVIEW_PLANNING_AUTHORIZATION.allows(
            ReviewPlanningPermission.CREATE_REVIEW_PLAN,
            PlanningAuthorizationContext(is_active_organization_user=actor.is_active),
        ):
            raise ReviewAuthorizationError("Active organization user required to create ReviewPlan")
        self._validate_title(title)
        self._validate_dates(planned_start_at, planned_end_at)
        plan = ReviewPlan(
            id=ReviewPlanId(uuid4()),
            organization_id=actor.organization_id,
            title=title,
            planned_start_at=planned_start_at,
            planned_end_at=planned_end_at,
            created_by=actor.id,
        )
        self._repository.add_plan(plan)
        return plan

    def list_plans(self, actor: User) -> tuple[ReviewPlan, ...]:
        self._require_active(actor)
        return self._repository.list_plans(actor.organization_id)

    def get_plan(self, actor: User, plan_id: ReviewPlanId) -> ReviewPlan:
        self._require_active(actor)
        plan = self._repository.get_plan(actor.organization_id, plan_id)
        if plan is None:
            raise LookupError("ReviewPlan not found")
        return plan

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
    ) -> ReviewCase:
        self._validate_title(title)
        self._validate_dates(planned_start_at, planned_end_at)
        policy = self._published_policy(actor, scenario_key, scenario_version)
        errors = policy.validate_case_input(scenario_data)
        if errors:
            raise ValueError("; ".join(errors))
        if (
            plan_id is not None
            and self._repository.get_plan(actor.organization_id, plan_id) is None
        ):
            raise LookupError("ReviewPlan not found")

        decision = policy.case_creation.decision()
        context = AuthorizationContext(is_active_organization_user=actor.is_active)
        if not policy.authorization.allows(decision.required_permission, context):
            raise ReviewAuthorizationError("Scenario does not allow this user to create ReviewCase")

        now = occurred_at or datetime.now(UTC)
        review_case = ReviewCase(
            id=ReviewCaseId(uuid4()),
            organization_id=actor.organization_id,
            plan_id=plan_id,
            scenario_key=scenario_key,
            scenario_version=scenario_version,
            title=title,
            lifecycle=decision.initial_lifecycle,
            created_by=actor.id,
            created_at=now,
            planned_start_at=planned_start_at,
            planned_end_at=planned_end_at,
            scenario_data=dict(scenario_data),
        )
        creator_memberships = tuple(
            CaseMember(
                organization_id=actor.organization_id,
                case_id=review_case.id,
                user_id=actor.id,
                role_key=role_key,
                joined_at=now,
            )
            for role_key in decision.creator_role_keys
        )
        for membership in creator_memberships:
            self._require_valid_case_role(policy, membership.role_key)

        # The request-scoped database transaction is the unit of work. These writes are
        # intentionally flushed in sequence but never committed here; any later failure rolls
        # all three back together.
        self._repository.add_case(review_case)
        for membership in creator_memberships:
            self._repository.add_case_member(membership)
        self._repository.add_activity(
            Activity(
                id=ActivityId(uuid4()),
                organization_id=actor.organization_id,
                subject=ReviewCaseActivitySubject(review_case.id),
                event_type=decision.activity_event_type,
                actor_id=actor.id,
                occurred_at=now,
                metadata={"creator_role_keys": decision.creator_role_keys},
            )
        )
        return review_case

    def list_cases(self, actor: User) -> tuple[ReviewCase, ...]:
        self._require_active(actor)
        visible: list[ReviewCase] = []
        for review_case in self._repository.list_cases(actor.organization_id):
            policy = self._registry.get(review_case.scenario_key, review_case.scenario_version)
            context = self._authorization_context(actor, review_case.id)
            if policy.authorization.allows(VIEW_CASE_PERMISSION, context):
                visible.append(review_case)
        return tuple(visible)

    def get_case(self, actor: User, case_id: ReviewCaseId) -> ReviewCase:
        review_case, policy, context = self._case_context(actor, case_id)
        if not policy.authorization.allows(VIEW_CASE_PERMISSION, context):
            raise ReviewAuthorizationError("ReviewCase is not visible to this user")
        return review_case

    def list_case_members(self, actor: User, case_id: ReviewCaseId) -> tuple[CaseMember, ...]:
        review_case, policy, context = self._case_context(actor, case_id)
        if not policy.authorization.allows(VIEW_CASE_PERMISSION, context):
            raise ReviewAuthorizationError("ReviewCase is not visible to this user")
        return self._repository.list_case_members(review_case.organization_id, review_case.id)

    def add_case_member(
        self,
        actor: User,
        case_id: ReviewCaseId,
        user_id: UserId,
        role_key: str,
        *,
        occurred_at: datetime | None = None,
    ) -> CaseMember:
        return self.add_case_member_result(
            actor,
            case_id,
            user_id,
            role_key,
            occurred_at=occurred_at,
        ).member

    def add_case_member_result(
        self,
        actor: User,
        case_id: ReviewCaseId,
        user_id: UserId,
        role_key: str,
        *,
        occurred_at: datetime | None = None,
    ) -> CaseMemberAddedResult:
        review_case, policy, context = self._case_context(actor, case_id)
        if not policy.authorization.allows(MANAGE_CASE_MEMBERS_PERMISSION, context):
            raise ReviewAuthorizationError("lead role required to manage CaseMember")
        target = self._users.get(user_id)
        if (
            target is None
            or target.organization_id != actor.organization_id
            or not target.is_active
        ):
            raise LookupError("Active organization User not found")
        self._require_valid_case_role(policy, role_key)
        now = occurred_at or datetime.now(UTC)
        member = CaseMember(
            organization_id=actor.organization_id,
            case_id=review_case.id,
            user_id=target.id,
            role_key=role_key,
            joined_at=now,
        )
        self._repository.add_case_member(member)
        activity_id = ActivityId(uuid4())
        self._repository.add_activity(
            Activity(
                id=activity_id,
                organization_id=actor.organization_id,
                subject=ReviewCaseActivitySubject(review_case.id),
                event_type="review_case.member_added",
                actor_id=actor.id,
                occurred_at=now,
                metadata={"user_id": str(target.id), "role_key": role_key},
            )
        )
        return CaseMemberAddedResult(member=member, activity_id=activity_id)

    def transition_case(
        self,
        actor: User,
        case_id: ReviewCaseId,
        action: str,
        *,
        reason: str | None = None,
        occurred_at: datetime | None = None,
    ) -> ReviewCase:
        review_case, policy, context = self._case_context(actor, case_id)
        if not policy.authorization.allows(TRANSITION_CASE_PERMISSION, context):
            raise ReviewAuthorizationError("lead role required to transition ReviewCase")
        target = policy.case_workflow.transition(
            review_case.lifecycle,
            action,
            ReviewCaseTransitionContext(reason=reason, all_findings_terminal=False),
        )
        now = occurred_at or datetime.now(UTC)
        updated = replace(
            review_case,
            lifecycle=target,
            started_at=(
                now
                if target is ReviewCaseLifecycle.IN_PROGRESS and review_case.started_at is None
                else review_case.started_at
            ),
            fieldwork_completed_at=(
                now
                if target is ReviewCaseLifecycle.AWAITING_CLOSURE
                else review_case.fieldwork_completed_at
            ),
            closed_at=(now if target is ReviewCaseLifecycle.CLOSED else review_case.closed_at),
        )
        if not self._repository.update_case(
            updated,
            expected_lifecycle=review_case.lifecycle,
        ):
            raise ConcurrentCaseTransitionError("Concurrent ReviewCase transition")
        metadata: dict[str, object] = {
            "action": action,
            "from_lifecycle": review_case.lifecycle.value,
            "to_lifecycle": target.value,
        }
        if reason is not None:
            metadata["reason"] = reason
        self._repository.add_activity(
            Activity(
                id=ActivityId(uuid4()),
                organization_id=actor.organization_id,
                subject=ReviewCaseActivitySubject(review_case.id),
                event_type="review_case.transitioned",
                actor_id=actor.id,
                occurred_at=now,
                metadata=metadata,
            )
        )
        return updated

    def _published_policy(
        self,
        actor: User,
        key: ScenarioKey,
        version: ScenarioVersion,
    ) -> ScenarioPolicy:
        policy = self._registry.get(key, version)
        scenario = self._scenario_catalog.get_by_key(actor.organization_id, key)
        if scenario is None or not scenario.is_active:
            raise LookupError("Scenario is not active for this organization")
        if (
            self._scenario_catalog.get_version(
                actor.organization_id,
                scenario.id,
                version,
            )
            is None
        ):
            raise LookupError("Scenario version is not published for this organization")
        return policy

    def _case_context(
        self,
        actor: User,
        case_id: ReviewCaseId,
    ) -> tuple[ReviewCase, ScenarioPolicy, AuthorizationContext]:
        self._require_active(actor)
        review_case = self._repository.get_case(actor.organization_id, case_id)
        if review_case is None:
            raise LookupError("ReviewCase not found")
        policy = self._registry.get(review_case.scenario_key, review_case.scenario_version)
        return review_case, policy, self._authorization_context(actor, case_id)

    def _authorization_context(
        self,
        actor: User,
        case_id: ReviewCaseId,
    ) -> AuthorizationContext:
        return build_authorization_context(self._repository, actor, case_id)

    @staticmethod
    def _require_valid_case_role(policy: ScenarioPolicy, role_key: str) -> None:
        grant = RoleGrant(
            role_key=role_key,
            actor_kind=ActorKind.USER,
            source=PermissionSource.DIRECT,
        )
        if not any(spec.accepts_grant(grant) for spec in policy.case_role_specs):
            raise ValueError(f"Scenario does not allow CaseMember role {role_key!r} for User")

    @staticmethod
    def _require_active(actor: User) -> None:
        if not actor.is_active:
            raise ReviewAuthorizationError("Active organization user required")

    @staticmethod
    def _validate_title(title: str) -> None:
        if not title.strip() or title != title.strip():
            raise ValueError("title must be a non-blank, unpadded string")

    @staticmethod
    def _validate_dates(start: datetime | None, end: datetime | None) -> None:
        if start is not None and start.utcoffset() is None:
            raise ValueError("planned_start_at must include UTC offset")
        if end is not None and end.utcoffset() is None:
            raise ValueError("planned_end_at must include UTC offset")
        if start is not None and end is not None and end < start:
            raise ValueError("planned_end_at must be greater than or equal to planned_start_at")
