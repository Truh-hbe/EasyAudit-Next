from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from easyaudit_next.review_core.domain.models import (
    ActionItemLifecycle,
    FindingLifecycle,
    ReviewCaseLifecycle,
    Scenario,
    ScenarioKey,
    ScenarioVersion,
    SubmissionPurpose,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActionItemTransitionContext,
    ActionItemWorkflowPolicy,
    ActorKind,
    AuthorizationContext,
    AuthorizationPolicy,
    CaseCreationDecision,
    FindingOperationContext,
    FindingOperationError,
    FindingOperationPolicy,
    FindingTransitionContext,
    FindingWorkflowPolicy,
    PermissionSource,
    ReviewCaseCreationPolicy,
    ReviewCaseTransitionContext,
    ReviewCaseWorkflowPolicy,
    RoleGrant,
    RoleSpecification,
    SubmissionDecision,
    SubmissionDecisionError,
    SubmissionPolicy,
    SubmissionRequest,
    WorkflowTransitionError,
)


class ProcessReviewCaseAction(StrEnum):
    SCHEDULE = "schedule"
    START = "start"
    FINISH_FIELDWORK = "finish_fieldwork"
    CLOSE = "close"
    CANCEL = "cancel"


class ProcessReviewFindingAction(StrEnum):
    ISSUE = "issue"
    SUBMIT_FOR_VERIFICATION = "submit_for_verification"
    APPROVE = "approve"
    REJECT = "reject"
    VOID = "void"
    REOPEN = "reopen"


class ProcessReviewActionItemAction(StrEnum):
    START = "start"
    COMPLETE = "complete"
    CANCEL = "cancel"
    REOPEN = "reopen"


class ProcessReviewSubmissionAction(StrEnum):
    SUBMIT_PLAN = "submit_plan"
    SUBMIT_FOR_VERIFICATION = "submit_for_verification"
    APPROVE = "approve"
    REJECT = "reject"


class ProcessReviewPermission(StrEnum):
    CREATE_CASE = "create_case"
    VIEW_CASE = "view_case"
    VIEW_FINDING = "view_finding"
    MANAGE_CASE_MEMBERS = "manage_case_members"
    TRANSITION_CASE = "transition_case"
    CREATE_FINDING = "create_finding"
    ISSUE_FINDING = "issue_finding"
    MANAGE_FINDING_PARTICIPANTS = "manage_finding_participants"
    CREATE_ACTION = "create_action"
    UPDATE_ASSIGNED_ACTION = "update_assigned_action"
    SUBMIT_RECTIFICATION = "submit_rectification"
    VERIFY_FINDING = "verify_finding"
    REOPEN_FINDING = "reopen_finding"


_USER_DIRECT = frozenset({ActorKind.USER})
_DEPARTMENT_ONLY = frozenset({ActorKind.DEPARTMENT})
_DIRECT_SOURCE = frozenset({PermissionSource.DIRECT})
_DEPARTMENT_SOURCE = frozenset({PermissionSource.DEPARTMENT_MEMBERSHIP})

PROCESS_REVIEW_CASE_ROLE_SPECS = (
    RoleSpecification("lead", _USER_DIRECT, _DIRECT_SOURCE),
    RoleSpecification("auditor", _USER_DIRECT, _DIRECT_SOURCE),
    RoleSpecification("reviewer", _USER_DIRECT, _DIRECT_SOURCE),
    RoleSpecification("observer", _USER_DIRECT, _DIRECT_SOURCE),
)

PROCESS_REVIEW_FINDING_ROLE_SPECS = (
    RoleSpecification(
        "responsible_department",
        _DEPARTMENT_ONLY,
        _DEPARTMENT_SOURCE,
    ),
    RoleSpecification("owner", _USER_DIRECT, _DIRECT_SOURCE),
    RoleSpecification("collaborator", _USER_DIRECT, _DIRECT_SOURCE),
)

PROCESS_REVIEW_ACTION_ROLE_SPECS = (
    RoleSpecification("primary", _USER_DIRECT, _DIRECT_SOURCE),
    RoleSpecification("collaborator", _USER_DIRECT, _DIRECT_SOURCE),
)


def _has_reason(reason: str | None) -> bool:
    return reason is not None and bool(reason.strip())


def _invalid_transition(
    entity: str,
    lifecycle: StrEnum,
    action: StrEnum,
) -> WorkflowTransitionError:
    return WorkflowTransitionError(
        f"{entity} cannot perform {action.value!r} from lifecycle {lifecycle.value!r}"
    )


def _required_text_fields(
    payload: Mapping[str, object],
    fields: tuple[str, ...],
) -> tuple[str, ...]:
    errors: list[str] = []
    for name in fields:
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{name} must be a non-blank string")
        elif value != value.strip():
            errors.append(f"{name} must not contain surrounding whitespace")
    return tuple(errors)


def _direct_user_role_keys(grants: frozenset[RoleGrant]) -> frozenset[str]:
    return frozenset(
        grant.role_key
        for grant in grants
        if grant.actor_kind is ActorKind.USER
        and grant.source is PermissionSource.DIRECT
    )


def _department_member_role_keys(grants: frozenset[RoleGrant]) -> frozenset[str]:
    return frozenset(
        grant.role_key
        for grant in grants
        if grant.actor_kind is ActorKind.DEPARTMENT
        and grant.source is PermissionSource.DEPARTMENT_MEMBERSHIP
    )


def _raise_submission_errors(errors: tuple[str, ...]) -> None:
    if errors:
        raise SubmissionDecisionError("; ".join(errors))


@dataclass(frozen=True, slots=True)
class ProcessReviewCaseCreationPolicy:
    def decision(self) -> CaseCreationDecision:
        return CaseCreationDecision(
            required_permission=ProcessReviewPermission.CREATE_CASE,
            initial_lifecycle=ReviewCaseLifecycle.DRAFT,
            creator_role_keys=("lead",),
            activity_event_type="review_case.created",
        )


@dataclass(frozen=True, slots=True)
class ProcessReviewCaseWorkflow:
    def transition(
        self,
        lifecycle: ReviewCaseLifecycle,
        action: str,
        context: ReviewCaseTransitionContext,
    ) -> ReviewCaseLifecycle:
        try:
            operation = ProcessReviewCaseAction(action)
        except ValueError as exc:
            raise WorkflowTransitionError(f"Unknown ReviewCase action: {action!r}") from exc

        if (
            lifecycle is ReviewCaseLifecycle.DRAFT
            and operation is ProcessReviewCaseAction.SCHEDULE
        ):
            return ReviewCaseLifecycle.SCHEDULED
        if (
            lifecycle is ReviewCaseLifecycle.SCHEDULED
            and operation is ProcessReviewCaseAction.START
        ):
            return ReviewCaseLifecycle.IN_PROGRESS
        if (
            lifecycle is ReviewCaseLifecycle.IN_PROGRESS
            and operation is ProcessReviewCaseAction.FINISH_FIELDWORK
        ):
            return ReviewCaseLifecycle.AWAITING_CLOSURE
        if (
            lifecycle is ReviewCaseLifecycle.AWAITING_CLOSURE
            and operation is ProcessReviewCaseAction.CLOSE
        ):
            if not context.all_findings_terminal:
                raise WorkflowTransitionError(
                    "ReviewCase cannot close until every Finding is closed or voided"
                )
            return ReviewCaseLifecycle.CLOSED
        if operation is ProcessReviewCaseAction.CANCEL and lifecycle in {
            ReviewCaseLifecycle.DRAFT,
            ReviewCaseLifecycle.SCHEDULED,
        }:
            if not _has_reason(context.reason):
                raise WorkflowTransitionError("Cancelling a ReviewCase requires a reason")
            return ReviewCaseLifecycle.CANCELLED
        raise _invalid_transition("ReviewCase", lifecycle, operation)


@dataclass(frozen=True, slots=True)
class ProcessReviewFindingWorkflow:
    def transition(
        self,
        lifecycle: FindingLifecycle,
        action: str,
        context: FindingTransitionContext,
    ) -> FindingLifecycle:
        try:
            operation = ProcessReviewFindingAction(action)
        except ValueError as exc:
            raise WorkflowTransitionError(f"Unknown Finding action: {action!r}") from exc

        if lifecycle is FindingLifecycle.OPEN and operation is ProcessReviewFindingAction.ISSUE:
            return FindingLifecycle.RECTIFYING
        if lifecycle is FindingLifecycle.OPEN and operation is ProcessReviewFindingAction.VOID:
            if not _has_reason(context.reason):
                raise WorkflowTransitionError("Voiding a Finding requires a reason")
            return FindingLifecycle.VOIDED
        if (
            lifecycle is FindingLifecycle.RECTIFYING
            and operation is ProcessReviewFindingAction.SUBMIT_FOR_VERIFICATION
        ):
            if context.non_cancelled_action_count < 1:
                raise WorkflowTransitionError(
                    "Finding requires at least one non-cancelled ActionItem before verification"
                )
            if not context.all_non_cancelled_actions_done:
                raise WorkflowTransitionError(
                    "Every non-cancelled ActionItem must be done before verification"
                )
            return FindingLifecycle.VERIFYING
        if (
            lifecycle is FindingLifecycle.VERIFYING
            and operation is ProcessReviewFindingAction.APPROVE
        ):
            return FindingLifecycle.CLOSED
        if (
            lifecycle is FindingLifecycle.VERIFYING
            and operation is ProcessReviewFindingAction.REJECT
        ):
            if not _has_reason(context.reason):
                raise WorkflowTransitionError("Rejecting a Finding requires a reason")
            return FindingLifecycle.RECTIFYING
        if (
            lifecycle is FindingLifecycle.CLOSED
            and operation is ProcessReviewFindingAction.REOPEN
        ):
            if not _has_reason(context.reason):
                raise WorkflowTransitionError("Reopening a Finding requires a reason")
            return FindingLifecycle.RECTIFYING
        raise _invalid_transition("Finding", lifecycle, operation)


@dataclass(frozen=True, slots=True)
class ProcessReviewFindingOperations:
    """Process Review v1 invariants for Finding operations beyond actor authorization."""

    def validate_create(self, context: FindingOperationContext) -> None:
        if context.case_lifecycle is not ReviewCaseLifecycle.IN_PROGRESS:
            raise FindingOperationError(
                "Process Review Finding can only be created while ReviewCase is in_progress"
            )

    def validate_participant_management(
        self,
        context: FindingOperationContext,
    ) -> None:
        if context.case_lifecycle not in {
            ReviewCaseLifecycle.IN_PROGRESS,
            ReviewCaseLifecycle.AWAITING_CLOSURE,
        }:
            raise FindingOperationError(
                "Finding participants can only be managed while ReviewCase is active"
            )
        if context.current_finding_lifecycle in {
            FindingLifecycle.CLOSED,
            FindingLifecycle.VOIDED,
        }:
            raise FindingOperationError(
                "Terminal Finding participants cannot be changed by ordinary business operations"
            )

    def validate_transition(
        self,
        action: str,
        context: FindingOperationContext,
    ) -> None:
        try:
            operation = ProcessReviewFindingAction(action)
        except ValueError as exc:
            raise FindingOperationError(f"Unknown Finding action: {action!r}") from exc

        if operation not in {
            ProcessReviewFindingAction.ISSUE,
            ProcessReviewFindingAction.VOID,
        }:
            return
        if context.current_finding_lifecycle is not FindingLifecycle.OPEN:
            raise FindingOperationError("Process Review issue/void requires an open Finding")
        if context.case_lifecycle not in {
            ReviewCaseLifecycle.IN_PROGRESS,
            ReviewCaseLifecycle.AWAITING_CLOSURE,
        }:
            raise FindingOperationError(
                "Process Review Finding cannot be issued or voided in this ReviewCase lifecycle"
            )
        if operation is ProcessReviewFindingAction.ISSUE:
            missing = tuple(
                role_key
                for role_key in ("responsible_department", "owner")
                if not context.has_participant_role(role_key)
            )
            if missing:
                raise FindingOperationError(
                    "Issuing a Process Review Finding requires participant role(s): "
                    + ", ".join(missing)
                )


@dataclass(frozen=True, slots=True)
class ProcessReviewActionWorkflow:
    def transition(
        self,
        lifecycle: ActionItemLifecycle,
        action: str,
        context: ActionItemTransitionContext,
    ) -> ActionItemLifecycle:
        try:
            operation = ProcessReviewActionItemAction(action)
        except ValueError as exc:
            raise WorkflowTransitionError(f"Unknown ActionItem action: {action!r}") from exc

        if (
            lifecycle is ActionItemLifecycle.TODO
            and operation is ProcessReviewActionItemAction.START
        ):
            return ActionItemLifecycle.IN_PROGRESS
        if (
            lifecycle is ActionItemLifecycle.IN_PROGRESS
            and operation is ProcessReviewActionItemAction.COMPLETE
        ):
            return ActionItemLifecycle.DONE
        if operation is ProcessReviewActionItemAction.CANCEL and lifecycle in {
            ActionItemLifecycle.TODO,
            ActionItemLifecycle.IN_PROGRESS,
        }:
            if not _has_reason(context.reason):
                raise WorkflowTransitionError("Cancelling an ActionItem requires a reason")
            return ActionItemLifecycle.CANCELLED
        if (
            lifecycle is ActionItemLifecycle.DONE
            and operation is ProcessReviewActionItemAction.REOPEN
        ):
            return ActionItemLifecycle.IN_PROGRESS
        raise _invalid_transition("ActionItem", lifecycle, operation)


@dataclass(frozen=True, slots=True)
class ProcessReviewAuthorizationPolicy:
    def allows(self, permission: str, context: AuthorizationContext) -> bool:
        try:
            requested = ProcessReviewPermission(permission)
        except ValueError:
            return False

        case_roles = _direct_user_role_keys(context.case_role_grants)
        finding_roles = _direct_user_role_keys(context.finding_role_grants)
        department_finding_roles = _department_member_role_keys(
            context.finding_role_grants
        )
        action_roles = _direct_user_role_keys(context.action_role_grants)

        if requested is ProcessReviewPermission.CREATE_CASE:
            return context.is_active_organization_user
        if requested in {
            ProcessReviewPermission.VIEW_CASE,
            ProcessReviewPermission.VIEW_FINDING,
        }:
            return bool(
                case_roles.intersection({"lead", "auditor", "reviewer", "observer"})
                or finding_roles.intersection({"owner", "collaborator"})
                or "responsible_department" in department_finding_roles
                or action_roles.intersection({"primary", "collaborator"})
            )
        if requested in {
            ProcessReviewPermission.MANAGE_CASE_MEMBERS,
            ProcessReviewPermission.TRANSITION_CASE,
        }:
            return "lead" in case_roles
        if requested in {
            ProcessReviewPermission.CREATE_FINDING,
            ProcessReviewPermission.ISSUE_FINDING,
            ProcessReviewPermission.MANAGE_FINDING_PARTICIPANTS,
        }:
            return bool(case_roles.intersection({"lead", "auditor"}))
        if requested is ProcessReviewPermission.CREATE_ACTION:
            return "owner" in finding_roles
        if requested is ProcessReviewPermission.UPDATE_ASSIGNED_ACTION:
            return bool(action_roles.intersection({"primary", "collaborator"}))
        if requested is ProcessReviewPermission.SUBMIT_RECTIFICATION:
            return "owner" in finding_roles
        if requested is ProcessReviewPermission.VERIFY_FINDING:
            return "reviewer" in case_roles
        if requested is ProcessReviewPermission.REOPEN_FINDING:
            return bool(case_roles.intersection({"lead", "auditor", "reviewer"}))
        return False


@dataclass(frozen=True, slots=True)
class ProcessReviewSubmissionPolicy:
    finding_workflow: FindingWorkflowPolicy = field(default_factory=ProcessReviewFindingWorkflow)

    def decide(self, request: SubmissionRequest) -> SubmissionDecision:
        try:
            operation = ProcessReviewSubmissionAction(request.action)
        except ValueError as exc:
            raise SubmissionDecisionError(
                f"Unknown Process Review submission action: {request.action!r}"
            ) from exc

        if operation is ProcessReviewSubmissionAction.SUBMIT_PLAN:
            self._require_rectification_stage(request, "plan")
            if request.current_lifecycle is not FindingLifecycle.RECTIFYING:
                raise SubmissionDecisionError(
                    "Rectification plan can only be submitted while Finding is rectifying"
                )
            _raise_submission_errors(
                _required_text_fields(request.payload, ("root_cause",))
            )
            return SubmissionDecision(
                required_permission=ProcessReviewPermission.SUBMIT_RECTIFICATION,
                target_lifecycle=FindingLifecycle.RECTIFYING,
                activity_event_type="finding.rectification_plan_submitted",
            )

        if operation is ProcessReviewSubmissionAction.SUBMIT_FOR_VERIFICATION:
            self._require_rectification_stage(request, "completion")
            _raise_submission_errors(_required_text_fields(request.payload, ("comment",)))
            target = self.finding_workflow.transition(
                request.current_lifecycle,
                ProcessReviewFindingAction.SUBMIT_FOR_VERIFICATION,
                request.transition_context,
            )
            return SubmissionDecision(
                required_permission=ProcessReviewPermission.SUBMIT_RECTIFICATION,
                target_lifecycle=target,
                activity_event_type="finding.submitted_for_verification",
            )

        if operation is ProcessReviewSubmissionAction.APPROVE:
            self._require_verification_result(request, "approved")
            target = self.finding_workflow.transition(
                request.current_lifecycle,
                ProcessReviewFindingAction.APPROVE,
                FindingTransitionContext(),
            )
            return SubmissionDecision(
                required_permission=ProcessReviewPermission.VERIFY_FINDING,
                target_lifecycle=target,
                activity_event_type="finding.approved",
            )

        self._require_verification_result(request, "rejected")
        _raise_submission_errors(_required_text_fields(request.payload, ("comment",)))
        comment = request.payload["comment"]
        assert isinstance(comment, str)
        target = self.finding_workflow.transition(
            request.current_lifecycle,
            ProcessReviewFindingAction.REJECT,
            FindingTransitionContext(reason=comment),
        )
        return SubmissionDecision(
            required_permission=ProcessReviewPermission.VERIFY_FINDING,
            target_lifecycle=target,
            activity_event_type="finding.rejected",
        )

    @staticmethod
    def _require_rectification_stage(
        request: SubmissionRequest,
        stage: str,
    ) -> None:
        if request.purpose is not SubmissionPurpose.RECTIFICATION:
            raise SubmissionDecisionError(
                f"{request.action} requires rectification Submission purpose"
            )
        if request.payload.get("stage") != stage:
            raise SubmissionDecisionError(
                f"{request.action} requires rectification stage {stage!r}"
            )

    @staticmethod
    def _require_verification_result(
        request: SubmissionRequest,
        result: str,
    ) -> None:
        if request.purpose is not SubmissionPurpose.VERIFICATION:
            raise SubmissionDecisionError(
                f"{request.action} requires verification Submission purpose"
            )
        if request.payload.get("result") != result:
            raise SubmissionDecisionError(
                f"{request.action} requires verification result {result!r}"
            )


@dataclass(frozen=True, slots=True)
class ProcessReviewV1BasePolicy:
    """Pre-rectification capabilities shared by the complete process_review@1 policy."""

    scenario: Scenario = field(
        default_factory=lambda: Scenario(
            key=ScenarioKey("process_review"),
            version=ScenarioVersion(1),
            name="Process Review",
        )
    )
    case_role_specs: tuple[RoleSpecification, ...] = PROCESS_REVIEW_CASE_ROLE_SPECS
    finding_participant_role_specs: tuple[RoleSpecification, ...] = (
        PROCESS_REVIEW_FINDING_ROLE_SPECS
    )
    action_assignee_role_specs: tuple[RoleSpecification, ...] = (
        PROCESS_REVIEW_ACTION_ROLE_SPECS
    )
    case_creation: ReviewCaseCreationPolicy = field(
        default_factory=ProcessReviewCaseCreationPolicy
    )
    case_workflow: ReviewCaseWorkflowPolicy = field(default_factory=ProcessReviewCaseWorkflow)
    finding_workflow: FindingWorkflowPolicy = field(default_factory=ProcessReviewFindingWorkflow)
    finding_operations: FindingOperationPolicy = field(
        default_factory=ProcessReviewFindingOperations
    )
    action_workflow: ActionItemWorkflowPolicy = field(default_factory=ProcessReviewActionWorkflow)
    authorization: AuthorizationPolicy = field(default_factory=ProcessReviewAuthorizationPolicy)
    submission_policy: SubmissionPolicy = field(default_factory=ProcessReviewSubmissionPolicy)

    def validate_case_input(self, payload: Mapping[str, object]) -> tuple[str, ...]:
        return _required_text_fields(payload, ("area_code", "review_type"))

    def validate_finding_input(self, payload: Mapping[str, object]) -> tuple[str, ...]:
        return _required_text_fields(payload, ("issue_type", "project_category"))
