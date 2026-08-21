from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from easyaudit_next.review_core.domain.models import (
    ActionItemLifecycle,
    AssignmentRole,
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
    AuthorizationContext,
    AuthorizationPolicy,
    FindingTransitionContext,
    FindingWorkflowPolicy,
    ReviewCaseTransitionContext,
    ReviewCaseWorkflowPolicy,
    SubmissionPolicy,
    WorkflowTransitionError,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry


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


class ProcessReviewPermission(StrEnum):
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

        case_roles = context.case_role_keys
        finding_roles = context.explicit_finding_role_keys
        department_roles = context.department_finding_role_keys
        action_roles = context.action_assignment_roles

        if requested in {
            ProcessReviewPermission.VIEW_CASE,
            ProcessReviewPermission.VIEW_FINDING,
        }:
            return bool(
                case_roles.intersection({"lead", "auditor", "reviewer", "observer"})
                or finding_roles
                or department_roles
                or action_roles
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
            return bool(
                action_roles.intersection(
                    {AssignmentRole.PRIMARY, AssignmentRole.COLLABORATOR}
                )
            )
        if requested is ProcessReviewPermission.SUBMIT_RECTIFICATION:
            return "owner" in finding_roles
        if requested is ProcessReviewPermission.VERIFY_FINDING:
            return "reviewer" in case_roles
        if requested is ProcessReviewPermission.REOPEN_FINDING:
            return bool(case_roles.intersection({"lead", "auditor", "reviewer"}))
        return False


@dataclass(frozen=True, slots=True)
class ProcessReviewSubmissionPolicy:
    def validate_submission(
        self,
        purpose: SubmissionPurpose,
        payload: Mapping[str, object],
    ) -> tuple[str, ...]:
        if purpose is SubmissionPurpose.RECTIFICATION:
            stage = payload.get("stage")
            if stage == "plan":
                return _required_text_fields(payload, ("root_cause",))
            if stage == "completion":
                return _required_text_fields(payload, ("comment",))
            return ("rectification stage must be 'plan' or 'completion'",)

        if purpose is SubmissionPurpose.VERIFICATION:
            result = payload.get("result")
            if result not in {"approved", "rejected"}:
                return ("verification result must be 'approved' or 'rejected'",)
            if result == "rejected":
                return _required_text_fields(payload, ("comment",))
            return ()

        return (f"submission purpose {purpose.value!r} is not defined by process_review@1",)


@dataclass(frozen=True, slots=True)
class ProcessReviewV1Policy:
    scenario: Scenario = field(
        default_factory=lambda: Scenario(
            key=ScenarioKey("process_review"),
            version=ScenarioVersion(1),
            name="Process Review",
        )
    )
    case_role_keys: tuple[str, ...] = ("lead", "auditor", "reviewer", "observer")
    finding_participant_role_keys: tuple[str, ...] = (
        "responsible_department",
        "owner",
        "collaborator",
    )
    case_workflow: ReviewCaseWorkflowPolicy = field(default_factory=ProcessReviewCaseWorkflow)
    finding_workflow: FindingWorkflowPolicy = field(default_factory=ProcessReviewFindingWorkflow)
    action_workflow: ActionItemWorkflowPolicy = field(default_factory=ProcessReviewActionWorkflow)
    authorization: AuthorizationPolicy = field(default_factory=ProcessReviewAuthorizationPolicy)
    submission_policy: SubmissionPolicy = field(default_factory=ProcessReviewSubmissionPolicy)

    def validate_case_input(self, payload: Mapping[str, object]) -> tuple[str, ...]:
        return _required_text_fields(payload, ("area_code", "review_type"))

    def validate_finding_input(self, payload: Mapping[str, object]) -> tuple[str, ...]:
        return _required_text_fields(payload, ("issue_type", "project_category"))


PROCESS_REVIEW_V1 = ProcessReviewV1Policy()


def register_process_review_v1(registry: ScenarioRegistry) -> ProcessReviewV1Policy:
    registry.register(PROCESS_REVIEW_V1)
    return PROCESS_REVIEW_V1
