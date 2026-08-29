from dataclasses import replace
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import uuid4

from easyaudit_next.platform.domain.ids import DepartmentId, UserId
from easyaudit_next.platform.domain.models import User
from easyaudit_next.platform.domain.repositories import DepartmentRepository, UserRepository
from easyaudit_next.review_core.application.authorization import build_authorization_context
from easyaudit_next.review_core.application.mutation_results import FindingParticipantAddedResult
from easyaudit_next.review_core.application.review_planning import ReviewAuthorizationError
from easyaudit_next.review_core.domain.ids import ActivityId, FindingId, ReviewCaseId
from easyaudit_next.review_core.domain.models import (
    Activity,
    Finding,
    FindingActivitySubject,
    FindingLifecycle,
    FindingParticipant,
    FindingSeverity,
    ParticipantActor,
    ReviewCase,
    UserActor,
)
from easyaudit_next.review_core.domain.repositories import ReviewCoreRepository
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActorKind,
    AuthorizationContext,
    FindingOperationContext,
    PermissionSource,
    RoleGrant,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioPolicy, ScenarioRegistry

VIEW_FINDING_PERMISSION = "view_finding"
CREATE_FINDING_PERMISSION = "create_finding"
MANAGE_FINDING_PARTICIPANTS_PERMISSION = "manage_finding_participants"


class ConcurrentFindingTransitionError(RuntimeError):
    """The persisted Finding lifecycle no longer matches the workflow input."""


class FindingLifecycleService:
    """M2.3 use cases for Finding discovery, participants, issue, and void."""

    def __init__(
        self,
        repository: ReviewCoreRepository,
        users: UserRepository,
        departments: DepartmentRepository,
        registry: ScenarioRegistry,
    ) -> None:
        self._repository = repository
        self._users = users
        self._departments = departments
        self._registry = registry

    def create_finding(
        self,
        actor: User,
        case_id: ReviewCaseId,
        title: str,
        severity: FindingSeverity,
        scenario_data: dict[str, object],
        *,
        description: str | None = None,
        occurred_at: datetime | None = None,
    ) -> Finding:
        review_case, policy = self._case_policy(actor, case_id)
        context = build_authorization_context(
            self._repository,
            actor,
            review_case.id,
        )
        if not policy.authorization.allows(CREATE_FINDING_PERMISSION, context):
            raise ReviewAuthorizationError("lead or auditor role required to create Finding")
        policy.finding_operations.validate_create(
            FindingOperationContext(case_lifecycle=review_case.lifecycle)
        )
        self._validate_title(title)
        errors = policy.validate_finding_input(scenario_data)
        if errors:
            raise ValueError("; ".join(errors))

        now = occurred_at or datetime.now(UTC)
        finding = Finding(
            id=FindingId(uuid4()),
            organization_id=actor.organization_id,
            case_id=review_case.id,
            title=title,
            description=description,
            severity=severity,
            lifecycle=FindingLifecycle.OPEN,
            raised_by=actor.id,
            raised_at=now,
            scenario_data=dict(scenario_data),
        )
        self._repository.add_finding(finding)
        self._repository.add_activity(
            Activity(
                id=ActivityId(uuid4()),
                organization_id=actor.organization_id,
                subject=FindingActivitySubject(finding.id),
                event_type="finding.created",
                actor_id=actor.id,
                occurred_at=now,
                metadata={"case_id": str(review_case.id)},
            )
        )
        return finding

    def list_findings(self, actor: User, case_id: ReviewCaseId) -> tuple[Finding, ...]:
        review_case, policy = self._case_policy(actor, case_id)
        visible: list[Finding] = []
        for finding in self._repository.list_findings(actor.organization_id, review_case.id):
            context = build_authorization_context(
                self._repository,
                actor,
                review_case.id,
                finding_id=finding.id,
            )
            if policy.authorization.allows(VIEW_FINDING_PERMISSION, context):
                visible.append(finding)
        return tuple(visible)

    def get_finding(self, actor: User, finding_id: FindingId) -> Finding:
        finding, _, policy, context = self._finding_context(actor, finding_id)
        if not policy.authorization.allows(VIEW_FINDING_PERMISSION, context):
            raise ReviewAuthorizationError("Finding is not visible to this user")
        return finding

    def list_participants(
        self,
        actor: User,
        finding_id: FindingId,
    ) -> tuple[FindingParticipant, ...]:
        finding, _, policy, context = self._finding_context(actor, finding_id)
        if not policy.authorization.allows(VIEW_FINDING_PERMISSION, context):
            raise ReviewAuthorizationError("Finding is not visible to this user")
        return self._repository.list_finding_participants(
            finding.organization_id,
            finding.id,
        )

    def add_participant(
        self,
        actor: User,
        finding_id: FindingId,
        participant_actor: ParticipantActor,
        role_key: str,
        *,
        occurred_at: datetime | None = None,
    ) -> FindingParticipant:
        return self.add_participant_result(
            actor,
            finding_id,
            participant_actor,
            role_key,
            occurred_at=occurred_at,
        ).participant

    def add_participant_result(
        self,
        actor: User,
        finding_id: FindingId,
        participant_actor: ParticipantActor,
        role_key: str,
        *,
        occurred_at: datetime | None = None,
    ) -> FindingParticipantAddedResult:
        finding, review_case, policy, context = self._finding_context(actor, finding_id)
        if not policy.authorization.allows(
            MANAGE_FINDING_PARTICIPANTS_PERMISSION,
            context,
        ):
            raise ReviewAuthorizationError(
                "lead or auditor role required to manage FindingParticipant"
            )
        policy.finding_operations.validate_participant_management(
            self._finding_operation_context(review_case, finding)
        )
        grant = self._participant_grant(participant_actor, role_key)
        self._validate_participant_grant(policy, grant, role_key)
        self._require_active_participant_actor(actor, participant_actor)

        finding = self._guard_participant_write(review_case, policy, finding)
        self._validate_participant_grant(policy, grant, role_key)
        self._require_active_participant_actor(actor, participant_actor)

        now = occurred_at or datetime.now(UTC)
        participant = FindingParticipant(
            organization_id=actor.organization_id,
            finding_id=finding.id,
            actor=participant_actor,
            role_key=role_key,
            assigned_at=now,
        )
        self._repository.add_finding_participant(participant)
        actor_kind, actor_id = self._participant_identity(participant_actor)
        activity_id = ActivityId(uuid4())
        self._repository.add_activity(
            Activity(
                id=activity_id,
                organization_id=actor.organization_id,
                subject=FindingActivitySubject(finding.id),
                event_type="finding.participant_added",
                actor_id=actor.id,
                occurred_at=now,
                metadata={
                    "participant_actor_kind": actor_kind.value,
                    "participant_actor_id": str(actor_id),
                    "role_key": role_key,
                },
            )
        )
        return FindingParticipantAddedResult(
            participant=participant,
            activity_id=activity_id,
        )

    def transition_finding(
        self,
        actor: User,
        finding_id: FindingId,
        action: str,
        *,
        reason: str | None = None,
        occurred_at: datetime | None = None,
    ) -> Finding:
        finding, review_case, policy, context = self._finding_context(actor, finding_id)
        if not policy.authorization.allows(VIEW_FINDING_PERMISSION, context):
            raise ReviewAuthorizationError("Finding is not visible to this user")
        operation_context = replace(
            self._finding_operation_context(
                review_case,
                finding,
                reason=reason,
            ),
            scenario_data=MappingProxyType(dict(finding.scenario_data)),
        )
        decision = policy.finding_direct_transitions.decide(action, operation_context)
        if not policy.authorization.allows(decision.required_permission, context):
            raise ReviewAuthorizationError(
                "Finding transition requires Scenario permission "
                f"{decision.required_permission!r}"
            )
        target = decision.target_lifecycle

        updated = replace(finding, lifecycle=target)
        if not self._repository.update_finding(
            updated,
            expected_lifecycle=finding.lifecycle,
        ):
            raise ConcurrentFindingTransitionError("Concurrent Finding transition")
        now = occurred_at or datetime.now(UTC)
        metadata: dict[str, object] = {
            "action": action,
            "from_lifecycle": finding.lifecycle.value,
            "to_lifecycle": target.value,
        }
        if reason is not None:
            metadata["reason"] = reason
        self._repository.add_activity(
            Activity(
                id=ActivityId(uuid4()),
                organization_id=actor.organization_id,
                subject=FindingActivitySubject(finding.id),
                event_type="finding.transitioned",
                actor_id=actor.id,
                occurred_at=now,
                metadata=metadata,
            )
        )
        return updated

    def _case_policy(
        self,
        actor: User,
        case_id: ReviewCaseId,
    ) -> tuple[ReviewCase, ScenarioPolicy]:
        self._require_active(actor)
        review_case = self._repository.get_case(actor.organization_id, case_id)
        if review_case is None:
            raise LookupError("ReviewCase not found")
        return (
            review_case,
            self._registry.get(review_case.scenario_key, review_case.scenario_version),
        )

    def _finding_context(
        self,
        actor: User,
        finding_id: FindingId,
    ) -> tuple[Finding, ReviewCase, ScenarioPolicy, AuthorizationContext]:
        self._require_active(actor)
        finding = self._repository.get_finding(actor.organization_id, finding_id)
        if finding is None:
            raise LookupError("Finding not found")
        review_case = self._repository.get_case(actor.organization_id, finding.case_id)
        if review_case is None:
            raise LookupError("ReviewCase not found")
        policy = self._registry.get(review_case.scenario_key, review_case.scenario_version)
        context = build_authorization_context(
            self._repository,
            actor,
            review_case.id,
            finding_id=finding.id,
        )
        return finding, review_case, policy, context

    def _finding_operation_context(
        self,
        review_case: ReviewCase,
        finding: Finding | None = None,
        *,
        reason: str | None = None,
    ) -> FindingOperationContext:
        participant_role_keys = (
            frozenset(
                participant.role_key
                for participant in self._repository.list_finding_participants(
                    review_case.organization_id,
                    finding.id,
                )
            )
            if finding is not None
            else frozenset()
        )
        return FindingOperationContext(
            case_lifecycle=review_case.lifecycle,
            current_finding_lifecycle=(finding.lifecycle if finding is not None else None),
            participant_role_keys=participant_role_keys,
            reason=reason,
        )

    def _guard_participant_write(
        self,
        review_case: ReviewCase,
        policy: ScenarioPolicy,
        finding: Finding,
    ) -> Finding:
        # A same-state CAS is a PostgreSQL serialization barrier: it locks the
        # Finding row until this transaction completes without inventing a new
        # lifecycle transition. A terminal transition that committed first makes
        # the expected-lifecycle predicate fail; one that starts later must wait.
        if not self._repository.update_finding(
            finding,
            expected_lifecycle=finding.lifecycle,
        ):
            raise ConcurrentFindingTransitionError("Concurrent Finding transition")
        guarded = self._repository.get_finding(finding.organization_id, finding.id)
        if guarded is None:
            raise LookupError("Finding not found")
        if guarded.lifecycle is not finding.lifecycle:
            raise ConcurrentFindingTransitionError("Concurrent Finding transition")
        policy.finding_operations.validate_participant_management(
            self._finding_operation_context(review_case, guarded)
        )
        return guarded

    @staticmethod
    def _validate_participant_grant(
        policy: ScenarioPolicy,
        grant: RoleGrant,
        role_key: str,
    ) -> None:
        if not any(
            specification.accepts_grant(grant)
            for specification in policy.finding_participant_role_specs
        ):
            raise ValueError(
                f"Scenario does not allow FindingParticipant role {role_key!r} "
                f"for {grant.actor_kind.value}"
            )

    def _require_active_participant_actor(
        self,
        request_actor: User,
        participant_actor: ParticipantActor,
    ) -> None:
        if isinstance(participant_actor, UserActor):
            target = self._users.get(UserId(participant_actor.user_id))
            if (
                target is None
                or target.organization_id != request_actor.organization_id
                or not target.is_active
            ):
                raise LookupError("Active organization User not found")
            return
        target_department = self._departments.get(
            DepartmentId(participant_actor.department_id)
        )
        if (
            target_department is None
            or target_department.organization_id != request_actor.organization_id
            or not target_department.is_active
        ):
            raise LookupError("Active organization Department not found")

    @staticmethod
    def _participant_grant(
        participant_actor: ParticipantActor,
        role_key: str,
    ) -> RoleGrant:
        if isinstance(participant_actor, UserActor):
            return RoleGrant(role_key, ActorKind.USER, PermissionSource.DIRECT)
        return RoleGrant(
            role_key,
            ActorKind.DEPARTMENT,
            PermissionSource.DEPARTMENT_MEMBERSHIP,
        )

    @staticmethod
    def _participant_identity(
        participant_actor: ParticipantActor,
    ) -> tuple[ActorKind, UserId | DepartmentId]:
        if isinstance(participant_actor, UserActor):
            return ActorKind.USER, participant_actor.user_id
        return ActorKind.DEPARTMENT, participant_actor.department_id

    @staticmethod
    def _require_active(actor: User) -> None:
        if not actor.is_active:
            raise ReviewAuthorizationError("Active organization user required")

    @staticmethod
    def _validate_title(title: str) -> None:
        if not title.strip() or title != title.strip():
            raise ValueError("title must be a non-blank, unpadded string")
