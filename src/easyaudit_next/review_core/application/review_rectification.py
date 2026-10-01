from dataclasses import replace
from datetime import UTC, datetime
from string import hexdigits
from uuid import uuid4

from easyaudit_next.platform.domain.ids import DepartmentId, UserId
from easyaudit_next.platform.domain.models import User
from easyaudit_next.platform.domain.repositories import DepartmentRepository, UserRepository
from easyaudit_next.review_core.application.authorization import (
    build_rectification_authorization_context,
)
from easyaudit_next.review_core.application.mutation_results import (
    ActionAssigneeAddedResult,
    RectificationSubmissionResult,
)
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
    FindingLifecycleService,
)
from easyaudit_next.review_core.application.review_planning import (
    ReviewAuthorizationError,
    ReviewPlanningService,
)
from easyaudit_next.review_core.domain.ids import (
    ActionItemId,
    ActivityId,
    EvidenceId,
    FindingId,
    ReviewCaseId,
    SubmissionId,
)
from easyaudit_next.review_core.domain.models import (
    ActionAssignee,
    ActionItem,
    ActionItemActivitySubject,
    ActionItemLifecycle,
    Activity,
    AssignmentRole,
    Evidence,
    Finding,
    ParticipantActor,
    ReviewCase,
    Submission,
    SubmissionActivitySubject,
    SubmissionPurpose,
    UserActor,
)
from easyaudit_next.review_core.domain.repositories import (
    RectificationRepository,
    ScenarioCatalogRepository,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActionItemOperationContext,
    ActionItemTransitionContext,
    ActorKind,
    AuthorizationContext,
    FindingOperationContext,
    FindingTransitionContext,
    PermissionSource,
    RoleGrant,
    SubmissionRequest,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioPolicy, ScenarioRegistry

VIEW_FINDING_PERMISSION = "view_finding"
CREATE_ACTION_PERMISSION = "create_action"
MANAGE_ACTION_ASSIGNEES_PERMISSION = "manage_action_assignees"
UPDATE_ASSIGNED_ACTION_PERMISSION = "update_assigned_action"
ADD_RECTIFICATION_EVIDENCE_PERMISSION = "add_rectification_evidence"


class ConcurrentActionItemTransitionError(RuntimeError):
    """The persisted ActionItem lifecycle no longer matches the workflow input."""


class ActionAwareReviewPlanningService(ReviewPlanningService):
    """M2.2 planning reads extended with M2.4 ActionAssignee visibility."""

    def __init__(
        self,
        repository: RectificationRepository,
        scenario_catalog: ScenarioCatalogRepository,
        users: UserRepository,
        registry: ScenarioRegistry,
    ) -> None:
        super().__init__(repository, scenario_catalog, users, registry)
        self._rectification_repository = repository

    def _authorization_context(
        self,
        actor: User,
        case_id: ReviewCaseId,
    ) -> AuthorizationContext:
        return build_rectification_authorization_context(
            self._rectification_repository,
            actor,
            case_id,
        )


class ActionAwareFindingLifecycleService(FindingLifecycleService):
    """M2.3 Finding use cases extended with persisted M2.4 Action facts and visibility."""

    def __init__(
        self,
        repository: RectificationRepository,
        users: UserRepository,
        departments: DepartmentRepository,
        registry: ScenarioRegistry,
    ) -> None:
        super().__init__(repository, users, departments, registry)
        self._rectification_repository = repository

    def list_findings(self, actor: User, case_id: ReviewCaseId) -> tuple[Finding, ...]:
        review_case, policy = self._case_policy(actor, case_id)
        visible: list[Finding] = []
        for finding in self._rectification_repository.list_findings(
            actor.organization_id,
            review_case.id,
        ):
            context = build_rectification_authorization_context(
                self._rectification_repository,
                actor,
                review_case.id,
                finding_id=finding.id,
            )
            if policy.authorization.allows(VIEW_FINDING_PERMISSION, context):
                visible.append(finding)
        return tuple(visible)

    def _finding_context(
        self,
        actor: User,
        finding_id: FindingId,
    ) -> tuple[Finding, ReviewCase, ScenarioPolicy, AuthorizationContext]:
        self._require_active(actor)
        finding = self._rectification_repository.get_finding(
            actor.organization_id,
            finding_id,
        )
        if finding is None:
            raise LookupError("Finding not found")
        review_case = self._rectification_repository.get_case(
            actor.organization_id,
            finding.case_id,
        )
        if review_case is None:
            raise LookupError("ReviewCase not found")
        policy = self._registry.get(review_case.scenario_key, review_case.scenario_version)
        context = build_rectification_authorization_context(
            self._rectification_repository,
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
                for participant in self._rectification_repository.list_finding_participants(
                    review_case.organization_id,
                    finding.id,
                )
            )
            if finding is not None
            else frozenset()
        )
        active_actions = (
            tuple(
                action
                for action in self._rectification_repository.list_action_items(
                    review_case.organization_id,
                    finding.id,
                )
                if action.lifecycle is not ActionItemLifecycle.CANCELLED
            )
            if finding is not None
            else ()
        )
        return FindingOperationContext(
            case_lifecycle=review_case.lifecycle,
            current_finding_lifecycle=(finding.lifecycle if finding is not None else None),
            participant_role_keys=participant_role_keys,
            non_cancelled_action_count=len(active_actions),
            all_non_cancelled_actions_done=(
                bool(active_actions)
                and all(action.lifecycle is ActionItemLifecycle.DONE for action in active_actions)
            ),
            reason=reason,
        )


class RectificationService:
    """Scenario-neutral M2.4 use cases for Action, Evidence, and rectification Submission."""

    def __init__(
        self,
        repository: RectificationRepository,
        users: UserRepository,
        departments: DepartmentRepository,
        registry: ScenarioRegistry,
    ) -> None:
        self._repository = repository
        self._users = users
        self._departments = departments
        self._registry = registry

    def create_action_item(
        self,
        actor: User,
        finding_id: FindingId,
        title: str,
        *,
        due_at: datetime | None = None,
        occurred_at: datetime | None = None,
    ) -> ActionItem:
        finding, review_case, policy, context = self._finding_context(actor, finding_id)
        if not policy.authorization.allows(CREATE_ACTION_PERMISSION, context):
            raise ReviewAuthorizationError("Finding owner role required to create ActionItem")
        finding = self._lock_expected_finding(actor, finding)
        policy.action_operations.validate_create(
            self._action_operation_context(review_case, finding)
        )
        self._validate_text(title, "title")
        self._require_aware_datetime(due_at, "due_at")

        now = occurred_at or datetime.now(UTC)
        action_item = ActionItem(
            id=ActionItemId(uuid4()),
            organization_id=actor.organization_id,
            finding_id=finding.id,
            title=title,
            lifecycle=ActionItemLifecycle.TODO,
            due_at=due_at,
        )
        self._repository.add_action_item(action_item)
        self._repository.add_activity(
            Activity(
                id=ActivityId(uuid4()),
                organization_id=actor.organization_id,
                subject=ActionItemActivitySubject(action_item.id),
                event_type="action_item.created",
                actor_id=actor.id,
                occurred_at=now,
                metadata={"finding_id": str(finding.id)},
            )
        )
        return action_item

    def list_action_items(
        self,
        actor: User,
        finding_id: FindingId,
    ) -> tuple[ActionItem, ...]:
        finding, _, policy, context = self._finding_context(actor, finding_id)
        if not policy.authorization.allows(VIEW_FINDING_PERMISSION, context):
            raise ReviewAuthorizationError("Finding is not visible to this user")
        return self._repository.list_action_items(actor.organization_id, finding.id)

    def get_action_item(self, actor: User, action_item_id: ActionItemId) -> ActionItem:
        action_item, _, _, policy, context = self._action_context(actor, action_item_id)
        if not policy.authorization.allows(VIEW_FINDING_PERMISSION, context):
            raise ReviewAuthorizationError("ActionItem is not visible to this user")
        return action_item

    def add_assignee(
        self,
        actor: User,
        action_item_id: ActionItemId,
        assignee_actor: ParticipantActor,
        role: AssignmentRole,
        *,
        occurred_at: datetime | None = None,
    ) -> ActionAssignee:
        return self.add_assignee_result(
            actor,
            action_item_id,
            assignee_actor,
            role,
            occurred_at=occurred_at,
        ).assignee

    def add_assignee_result(
        self,
        actor: User,
        action_item_id: ActionItemId,
        assignee_actor: ParticipantActor,
        role: AssignmentRole,
        *,
        occurred_at: datetime | None = None,
    ) -> ActionAssigneeAddedResult:
        action_item, finding, review_case, policy, context = self._action_context(
            actor,
            action_item_id,
        )
        if not policy.authorization.allows(MANAGE_ACTION_ASSIGNEES_PERMISSION, context):
            raise ReviewAuthorizationError("Finding owner role required to manage ActionAssignee")
        finding = self._lock_expected_finding(actor, finding)
        action_item = self._reload_action(actor, action_item.id, finding.id)
        policy.action_operations.validate_assignee_management(
            self._action_operation_context(review_case, finding, action_item)
        )
        grant = self._assignee_grant(assignee_actor, role)
        if not any(
            specification.accepts_grant(grant)
            for specification in policy.action_assignee_role_specs
        ):
            raise ValueError(
                f"Scenario does not allow ActionAssignee role {role.value!r} "
                f"for {grant.actor_kind.value}"
            )
        self._require_active_assignee_actor(actor, assignee_actor)

        now = occurred_at or datetime.now(UTC)
        assignee = ActionAssignee(
            organization_id=actor.organization_id,
            action_item_id=action_item.id,
            actor=assignee_actor,
            role=role,
            assigned_at=now,
        )
        self._repository.add_action_assignee(assignee)
        actor_kind, actor_id = self._participant_identity(assignee_actor)
        activity_id = ActivityId(uuid4())
        self._repository.add_activity(
            Activity(
                id=activity_id,
                organization_id=actor.organization_id,
                subject=ActionItemActivitySubject(action_item.id),
                event_type="action_item.assignee_added",
                actor_id=actor.id,
                occurred_at=now,
                metadata={
                    "assignee_actor_kind": actor_kind.value,
                    "assignee_actor_id": str(actor_id),
                    "role": role.value,
                },
            )
        )
        return ActionAssigneeAddedResult(assignee=assignee, activity_id=activity_id)

    def list_assignees(
        self,
        actor: User,
        action_item_id: ActionItemId,
    ) -> tuple[ActionAssignee, ...]:
        action_item, _, _, policy, context = self._action_context(actor, action_item_id)
        if not policy.authorization.allows(VIEW_FINDING_PERMISSION, context):
            raise ReviewAuthorizationError("ActionItem is not visible to this user")
        return self._repository.list_action_assignees(
            actor.organization_id,
            action_item.id,
        )

    def transition_action_item(
        self,
        actor: User,
        action_item_id: ActionItemId,
        action: str,
        *,
        reason: str | None = None,
        occurred_at: datetime | None = None,
    ) -> ActionItem:
        action_item, finding, review_case, policy, context = self._action_context(
            actor,
            action_item_id,
        )
        if not policy.authorization.allows(UPDATE_ASSIGNED_ACTION_PERMISSION, context):
            raise ReviewAuthorizationError("Action assignee role required to transition ActionItem")
        finding = self._lock_expected_finding(actor, finding)
        operation_context = self._action_operation_context(
            review_case,
            finding,
            action_item,
            reason=reason,
        )
        policy.action_operations.validate_transition(action, operation_context)
        target = policy.action_workflow.transition(
            action_item.lifecycle,
            action,
            ActionItemTransitionContext(reason=reason),
        )
        now = occurred_at or datetime.now(UTC)
        updated = replace(
            action_item,
            lifecycle=target,
            completed_at=(now if target is ActionItemLifecycle.DONE else None),
        )
        if not self._repository.update_action_item(
            updated,
            expected_lifecycle=action_item.lifecycle,
        ):
            raise ConcurrentActionItemTransitionError("Concurrent ActionItem transition")
        metadata: dict[str, object] = {
            "action": action,
            "from_lifecycle": action_item.lifecycle.value,
            "to_lifecycle": target.value,
        }
        if reason is not None:
            metadata["reason"] = reason
        self._repository.add_activity(
            Activity(
                id=ActivityId(uuid4()),
                organization_id=actor.organization_id,
                subject=ActionItemActivitySubject(action_item.id),
                event_type="action_item.transitioned",
                actor_id=actor.id,
                occurred_at=now,
                metadata=metadata,
            )
        )
        return updated

    def authorize_evidence_registration(
        self,
        actor: User,
        action_item_id: ActionItemId,
    ) -> None:
        """Pre-authorization for an upload: the permission and Action checks of
        `register_evidence`, without the Finding lock.

        Advisory only. It lets the caller refuse an unauthorized upload before any byte is
        stored; `register_evidence` repeats every check under the lock and decides.
        """
        action_item, finding, review_case, policy, context = self._action_context(
            actor,
            action_item_id,
        )
        self._require_evidence_permission(policy, context)
        policy.action_operations.validate_evidence_registration(
            self._action_operation_context(review_case, finding, action_item)
        )

    @staticmethod
    def _require_evidence_permission(
        policy: ScenarioPolicy, context: AuthorizationContext
    ) -> None:
        if not policy.authorization.allows(ADD_RECTIFICATION_EVIDENCE_PERMISSION, context):
            raise ReviewAuthorizationError(
                "Finding owner or Action assignee role required to register Evidence"
            )

    def register_evidence(
        self,
        actor: User,
        action_item_id: ActionItemId,
        storage_key: str,
        original_name: str,
        size_bytes: int,
        sha256: str,
        *,
        content_type: str | None = None,
        description: str | None = None,
        occurred_at: datetime | None = None,
    ) -> Evidence:
        action_item, finding, review_case, policy, context = self._action_context(
            actor,
            action_item_id,
        )
        self._require_evidence_permission(policy, context)
        finding = self._lock_expected_finding(actor, finding)
        action_item = self._reload_action(actor, action_item.id, finding.id)
        policy.action_operations.validate_evidence_registration(
            self._action_operation_context(review_case, finding, action_item)
        )
        self._validate_text(storage_key, "storage_key")
        self._validate_text(original_name, "original_name")
        if content_type is not None:
            self._validate_text(content_type, "content_type")
        if size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        if len(sha256) != 64 or any(character not in hexdigits.lower() for character in sha256):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        if sha256 != sha256.lower():
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")

        now = occurred_at or datetime.now(UTC)
        evidence = Evidence(
            id=EvidenceId(uuid4()),
            organization_id=actor.organization_id,
            action_item_id=action_item.id,
            storage_key=storage_key,
            original_name=original_name,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
            description=description,
            uploaded_by=actor.id,
            created_at=now,
        )
        self._repository.add_evidence(evidence)
        self._repository.add_activity(
            Activity(
                id=ActivityId(uuid4()),
                organization_id=actor.organization_id,
                subject=ActionItemActivitySubject(action_item.id),
                event_type="action_item.evidence_registered",
                actor_id=actor.id,
                occurred_at=now,
                metadata={"evidence_id": str(evidence.id), "sha256": evidence.sha256},
            )
        )
        return evidence

    def list_evidences(
        self,
        actor: User,
        action_item_id: ActionItemId,
    ) -> tuple[Evidence, ...]:
        action_item, _, _, policy, context = self._action_context(actor, action_item_id)
        if not policy.authorization.allows(VIEW_FINDING_PERMISSION, context):
            raise ReviewAuthorizationError("ActionItem is not visible to this user")
        return self._repository.list_evidences(actor.organization_id, action_item.id)

    def submit_rectification(
        self,
        actor: User,
        finding_id: FindingId,
        action: str,
        payload: dict[str, object],
        *,
        occurred_at: datetime | None = None,
    ) -> tuple[Submission, Finding]:
        result = self.submit_rectification_result(
            actor,
            finding_id,
            action,
            payload,
            occurred_at=occurred_at,
        )
        return result.submission, result.finding

    def submit_rectification_result(
        self,
        actor: User,
        finding_id: FindingId,
        action: str,
        payload: dict[str, object],
        *,
        occurred_at: datetime | None = None,
    ) -> RectificationSubmissionResult:
        finding, review_case, policy, context = self._finding_context(actor, finding_id)
        if not policy.authorization.allows(VIEW_FINDING_PERMISSION, context):
            raise ReviewAuthorizationError("Finding is not visible to this user")
        finding = self._lock_expected_finding(actor, finding)
        active_actions = tuple(
            action_item
            for action_item in self._repository.list_action_items(
                actor.organization_id,
                finding.id,
            )
            if action_item.lifecycle is not ActionItemLifecycle.CANCELLED
        )
        decision = policy.submission_policy.decide(
            SubmissionRequest(
                current_lifecycle=finding.lifecycle,
                action=action,
                purpose=SubmissionPurpose.RECTIFICATION,
                payload=dict(payload),
                transition_context=FindingTransitionContext(
                    non_cancelled_action_count=len(active_actions),
                    all_non_cancelled_actions_done=(
                        bool(active_actions)
                        and all(
                            action_item.lifecycle is ActionItemLifecycle.DONE
                            for action_item in active_actions
                        )
                    ),
                ),
            )
        )
        if not policy.authorization.allows(decision.required_permission, context):
            raise ReviewAuthorizationError(
                "Scenario permission required for rectification Submission"
            )

        now = occurred_at or datetime.now(UTC)
        updated_finding = finding
        if decision.target_lifecycle is not finding.lifecycle:
            updated_finding = replace(finding, lifecycle=decision.target_lifecycle)
            if not self._repository.update_finding(
                updated_finding,
                expected_lifecycle=finding.lifecycle,
            ):
                raise ConcurrentFindingTransitionError("Concurrent Finding transition")

        submission = Submission(
            id=SubmissionId(uuid4()),
            organization_id=actor.organization_id,
            case_id=review_case.id,
            finding_id=finding.id,
            purpose=SubmissionPurpose.RECTIFICATION,
            submitted_by=actor.id,
            submitted_at=now,
            payload=dict(payload),
        )
        self._repository.add_submission(submission)
        activity_id = ActivityId(uuid4())
        self._repository.add_activity(
            Activity(
                id=activity_id,
                organization_id=actor.organization_id,
                subject=SubmissionActivitySubject(submission.id),
                event_type=decision.activity_event_type,
                actor_id=actor.id,
                occurred_at=now,
                metadata={
                    "action": action,
                    "finding_id": str(finding.id),
                    "from_lifecycle": finding.lifecycle.value,
                    "to_lifecycle": updated_finding.lifecycle.value,
                },
            )
        )
        return RectificationSubmissionResult(
            submission=submission,
            finding=updated_finding,
            activity_id=activity_id,
        )

    def list_rectification_submissions(
        self,
        actor: User,
        finding_id: FindingId,
    ) -> tuple[Submission, ...]:
        finding, _, policy, context = self._finding_context(actor, finding_id)
        if not policy.authorization.allows(VIEW_FINDING_PERMISSION, context):
            raise ReviewAuthorizationError("Finding is not visible to this user")
        return tuple(
            submission
            for submission in self._repository.list_submissions(
                actor.organization_id,
                finding.id,
            )
            if submission.purpose is SubmissionPurpose.RECTIFICATION
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
        context = build_rectification_authorization_context(
            self._repository,
            actor,
            review_case.id,
            finding_id=finding.id,
        )
        return finding, review_case, policy, context

    def _action_context(
        self,
        actor: User,
        action_item_id: ActionItemId,
    ) -> tuple[ActionItem, Finding, ReviewCase, ScenarioPolicy, AuthorizationContext]:
        self._require_active(actor)
        action_item = self._repository.get_action_item(actor.organization_id, action_item_id)
        if action_item is None:
            raise LookupError("ActionItem not found")
        finding = self._repository.get_finding(actor.organization_id, action_item.finding_id)
        if finding is None:
            raise LookupError("Finding not found")
        review_case = self._repository.get_case(actor.organization_id, finding.case_id)
        if review_case is None:
            raise LookupError("ReviewCase not found")
        policy = self._registry.get(review_case.scenario_key, review_case.scenario_version)
        context = build_rectification_authorization_context(
            self._repository,
            actor,
            review_case.id,
            finding_id=finding.id,
            action_item_id=action_item.id,
        )
        return action_item, finding, review_case, policy, context

    def _lock_expected_finding(self, actor: User, expected: Finding) -> Finding:
        locked = self._repository.lock_finding_for_rectification(
            actor.organization_id,
            expected.id,
        )
        if locked is None:
            raise LookupError("Finding not found")
        if locked.lifecycle is not expected.lifecycle:
            raise ConcurrentFindingTransitionError("Concurrent Finding transition")
        return locked

    def _reload_action(
        self,
        actor: User,
        action_item_id: ActionItemId,
        expected_finding_id: FindingId,
    ) -> ActionItem:
        action_item = self._repository.get_action_item(actor.organization_id, action_item_id)
        if action_item is None or action_item.finding_id != expected_finding_id:
            raise LookupError("ActionItem not found")
        return action_item

    def _action_operation_context(
        self,
        review_case: ReviewCase,
        finding: Finding,
        action_item: ActionItem | None = None,
        *,
        reason: str | None = None,
    ) -> ActionItemOperationContext:
        assignee_role_keys = (
            frozenset(
                assignee.role.value
                for assignee in self._repository.list_action_assignees(
                    review_case.organization_id,
                    action_item.id,
                )
            )
            if action_item is not None
            else frozenset()
        )
        return ActionItemOperationContext(
            case_lifecycle=review_case.lifecycle,
            finding_lifecycle=finding.lifecycle,
            current_action_lifecycle=(
                action_item.lifecycle if action_item is not None else None
            ),
            assignee_role_keys=assignee_role_keys,
            reason=reason,
        )

    def _require_active_assignee_actor(
        self,
        request_actor: User,
        assignee_actor: ParticipantActor,
    ) -> None:
        if isinstance(assignee_actor, UserActor):
            target = self._users.get(UserId(assignee_actor.user_id))
            if (
                target is None
                or target.organization_id != request_actor.organization_id
                or not target.is_active
            ):
                raise LookupError("Active organization User not found")
            return
        target_department = self._departments.get(
            DepartmentId(assignee_actor.department_id)
        )
        if (
            target_department is None
            or target_department.organization_id != request_actor.organization_id
            or not target_department.is_active
        ):
            raise LookupError("Active organization Department not found")

    @staticmethod
    def _assignee_grant(
        assignee_actor: ParticipantActor,
        role: AssignmentRole,
    ) -> RoleGrant:
        if isinstance(assignee_actor, UserActor):
            return RoleGrant(role.value, ActorKind.USER, PermissionSource.DIRECT)
        return RoleGrant(
            role.value,
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
    def _validate_text(value: str, field_name: str) -> None:
        if not value.strip() or value != value.strip():
            raise ValueError(f"{field_name} must be a non-blank, unpadded string")

    @staticmethod
    def _require_aware_datetime(value: datetime | None, field_name: str) -> None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError(f"{field_name} must include a UTC offset")
