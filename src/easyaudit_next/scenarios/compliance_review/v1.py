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
    ActionItemOperationContext,
    ActionItemOperationError,
    ActionItemOperationPolicy,
    ActionItemTransitionContext,
    ActionItemWorkflowPolicy,
    ActorKind,
    AuthorizationContext,
    AuthorizationPolicy,
    CaseCreationDecision,
    CollaborationRecipientIntent,
    CollaborationRecipientPolicy,
    DirectFindingTransitionDecision,
    DirectFindingTransitionPolicy,
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


class ComplianceReviewCaseAction(StrEnum):
    SCHEDULE = "schedule"
    START = "start"
    FINISH_FIELDWORK = "finish_fieldwork"
    CLOSE = "close"
    CANCEL = "cancel"


class ComplianceReviewFindingAction(StrEnum):
    ISSUE = "issue"
    ACCEPT_OBSERVATION = "accept_observation"
    SUBMIT_FOR_VERIFICATION = "submit_for_verification"
    APPROVE = "approve"
    REJECT = "reject"
    VOID = "void"
    REOPEN = "reopen"


class ComplianceReviewFindingType(StrEnum):
    NONCONFORMITY = "nonconformity"
    OBSERVATION = "observation"


class ComplianceReviewActionItemAction(StrEnum):
    START = "start"
    COMPLETE = "complete"
    CANCEL = "cancel"
    REOPEN = "reopen"


class ComplianceReviewSubmissionAction(StrEnum):
    SUBMIT_PLAN = "submit_plan"
    SUBMIT_FOR_VERIFICATION = "submit_for_verification"
    APPROVE = "approve"
    REJECT = "reject"


class ComplianceReviewPermission(StrEnum):
    CREATE_CASE = "create_case"
    VIEW_CASE = "view_case"
    VIEW_FINDING = "view_finding"
    MANAGE_CASE_MEMBERS = "manage_case_members"
    TRANSITION_CASE = "transition_case"
    CREATE_FINDING = "create_finding"
    ISSUE_FINDING = "issue_finding"
    ACCEPT_OBSERVATION = "accept_observation"
    MANAGE_FINDING_PARTICIPANTS = "manage_finding_participants"
    CREATE_ACTION = "create_action"
    MANAGE_ACTION_ASSIGNEES = "manage_action_assignees"
    UPDATE_ASSIGNED_ACTION = "update_assigned_action"
    ADD_RECTIFICATION_EVIDENCE = "add_rectification_evidence"
    SUBMIT_RECTIFICATION = "submit_rectification"
    VERIFY_FINDING = "verify_finding"
    REOPEN_FINDING = "reopen_finding"


_USER_DIRECT = frozenset({ActorKind.USER})
_DEPARTMENT_ONLY = frozenset({ActorKind.DEPARTMENT})
_DIRECT_SOURCE = frozenset({PermissionSource.DIRECT})
_DEPARTMENT_SOURCE = frozenset({PermissionSource.DEPARTMENT_MEMBERSHIP})
_ACTIVE_CASE_LIFECYCLES = {
    ReviewCaseLifecycle.IN_PROGRESS,
    ReviewCaseLifecycle.AWAITING_CLOSURE,
}

COMPLIANCE_REVIEW_CASE_ROLE_SPECS = (
    RoleSpecification("lead", _USER_DIRECT, _DIRECT_SOURCE),
    RoleSpecification("auditor", _USER_DIRECT, _DIRECT_SOURCE),
    RoleSpecification("reviewer", _USER_DIRECT, _DIRECT_SOURCE),
    RoleSpecification("observer", _USER_DIRECT, _DIRECT_SOURCE),
)

COMPLIANCE_REVIEW_FINDING_ROLE_SPECS = (
    RoleSpecification(
        "responsible_department",
        _DEPARTMENT_ONLY,
        _DEPARTMENT_SOURCE,
    ),
    RoleSpecification("owner", _USER_DIRECT, _DIRECT_SOURCE),
    RoleSpecification("collaborator", _USER_DIRECT, _DIRECT_SOURCE),
)

COMPLIANCE_REVIEW_ACTION_ROLE_SPECS = (
    RoleSpecification("primary", _USER_DIRECT, _DIRECT_SOURCE),
    RoleSpecification("collaborator", _USER_DIRECT, _DIRECT_SOURCE),
)


def _has_reason(reason: str | None) -> bool:
    return reason is not None and bool(reason.strip())


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


def _finding_type(context: FindingOperationContext) -> ComplianceReviewFindingType:
    raw = context.scenario_data.get("finding_type")
    try:
        return ComplianceReviewFindingType(raw)
    except (TypeError, ValueError) as exc:
        raise FindingOperationError("Compliance Finding requires a valid finding_type") from exc


def _raise_submission_errors(errors: tuple[str, ...]) -> None:
    if errors:
        raise SubmissionDecisionError("; ".join(errors))


@dataclass(frozen=True, slots=True)
class ComplianceReviewCaseCreationPolicy:
    def decision(self) -> CaseCreationDecision:
        return CaseCreationDecision(
            required_permission=ComplianceReviewPermission.CREATE_CASE,
            initial_lifecycle=ReviewCaseLifecycle.DRAFT,
            creator_role_keys=("lead",),
            activity_event_type="review_case.created",
        )


@dataclass(frozen=True, slots=True)
class ComplianceReviewCaseWorkflow:
    def transition(
        self,
        lifecycle: ReviewCaseLifecycle,
        action: str,
        context: ReviewCaseTransitionContext,
    ) -> ReviewCaseLifecycle:
        try:
            operation = ComplianceReviewCaseAction(action)
        except ValueError as exc:
            raise WorkflowTransitionError(f"Unknown ReviewCase action: {action!r}") from exc

        if (
            lifecycle is ReviewCaseLifecycle.DRAFT
            and operation is ComplianceReviewCaseAction.SCHEDULE
        ):
            return ReviewCaseLifecycle.SCHEDULED
        if (
            lifecycle is ReviewCaseLifecycle.SCHEDULED
            and operation is ComplianceReviewCaseAction.START
        ):
            return ReviewCaseLifecycle.IN_PROGRESS
        if (
            lifecycle is ReviewCaseLifecycle.IN_PROGRESS
            and operation is ComplianceReviewCaseAction.FINISH_FIELDWORK
        ):
            return ReviewCaseLifecycle.AWAITING_CLOSURE
        if (
            lifecycle is ReviewCaseLifecycle.AWAITING_CLOSURE
            and operation is ComplianceReviewCaseAction.CLOSE
        ):
            if not context.all_findings_terminal:
                raise WorkflowTransitionError(
                    "ReviewCase cannot close until every Finding is closed or voided"
                )
            return ReviewCaseLifecycle.CLOSED
        if operation is ComplianceReviewCaseAction.CANCEL and lifecycle in {
            ReviewCaseLifecycle.DRAFT,
            ReviewCaseLifecycle.SCHEDULED,
        }:
            if not _has_reason(context.reason):
                raise WorkflowTransitionError("Cancelling a ReviewCase requires a reason")
            return ReviewCaseLifecycle.CANCELLED
        raise WorkflowTransitionError(
            f"ReviewCase cannot perform {operation.value!r} from lifecycle {lifecycle.value!r}"
        )


@dataclass(frozen=True, slots=True)
class ComplianceReviewFindingWorkflow:
    def transition(
        self,
        lifecycle: FindingLifecycle,
        action: str,
        context: FindingTransitionContext,
    ) -> FindingLifecycle:
        try:
            operation = ComplianceReviewFindingAction(action)
        except ValueError as exc:
            raise WorkflowTransitionError(f"Unknown Finding action: {action!r}") from exc

        if lifecycle is FindingLifecycle.OPEN and operation is ComplianceReviewFindingAction.ISSUE:
            return FindingLifecycle.RECTIFYING
        if (
            lifecycle is FindingLifecycle.OPEN
            and operation is ComplianceReviewFindingAction.ACCEPT_OBSERVATION
        ):
            return FindingLifecycle.CLOSED
        if lifecycle is FindingLifecycle.OPEN and operation is ComplianceReviewFindingAction.VOID:
            if not _has_reason(context.reason):
                raise WorkflowTransitionError("Voiding a Finding requires a reason")
            return FindingLifecycle.VOIDED
        if (
            lifecycle is FindingLifecycle.RECTIFYING
            and operation is ComplianceReviewFindingAction.SUBMIT_FOR_VERIFICATION
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
            and operation is ComplianceReviewFindingAction.APPROVE
        ):
            return FindingLifecycle.CLOSED
        if (
            lifecycle is FindingLifecycle.VERIFYING
            and operation is ComplianceReviewFindingAction.REJECT
        ):
            if not _has_reason(context.reason):
                raise WorkflowTransitionError("Rejecting a Finding requires a reason")
            return FindingLifecycle.RECTIFYING
        if (
            lifecycle is FindingLifecycle.CLOSED
            and operation is ComplianceReviewFindingAction.REOPEN
        ):
            if not _has_reason(context.reason):
                raise WorkflowTransitionError("Reopening a Finding requires a reason")
            return FindingLifecycle.RECTIFYING
        raise WorkflowTransitionError(
            f"Finding cannot perform {operation.value!r} from lifecycle {lifecycle.value!r}"
        )


@dataclass(frozen=True, slots=True)
class ComplianceReviewFindingOperations:
    def validate_create(self, context: FindingOperationContext) -> None:
        if context.case_lifecycle is not ReviewCaseLifecycle.IN_PROGRESS:
            raise FindingOperationError(
                "Compliance Review Finding can only be created while ReviewCase is in_progress"
            )

    def validate_participant_management(self, context: FindingOperationContext) -> None:
        if context.case_lifecycle not in _ACTIVE_CASE_LIFECYCLES:
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

    def validate_transition(self, action: str, context: FindingOperationContext) -> None:
        try:
            operation = ComplianceReviewFindingAction(action)
        except ValueError as exc:
            raise FindingOperationError(f"Unknown Finding action: {action!r}") from exc
        if operation not in {
            ComplianceReviewFindingAction.ISSUE,
            ComplianceReviewFindingAction.ACCEPT_OBSERVATION,
            ComplianceReviewFindingAction.VOID,
        }:
            return
        if context.current_finding_lifecycle is not FindingLifecycle.OPEN:
            raise FindingOperationError("Compliance direct transition requires an open Finding")
        if context.case_lifecycle not in _ACTIVE_CASE_LIFECYCLES:
            raise FindingOperationError(
                "Compliance Finding cannot transition directly in this ReviewCase lifecycle"
            )
        finding_type = _finding_type(context)
        if operation is ComplianceReviewFindingAction.ISSUE:
            if finding_type is not ComplianceReviewFindingType.NONCONFORMITY:
                raise FindingOperationError("Only a nonconformity can be issued for rectification")
            missing = tuple(
                role_key
                for role_key in ("responsible_department", "owner")
                if not context.has_participant_role(role_key)
            )
            if missing:
                raise FindingOperationError(
                    "Issuing a compliance nonconformity requires participant role(s): "
                    + ", ".join(missing)
                )
        if operation is ComplianceReviewFindingAction.ACCEPT_OBSERVATION:
            if finding_type is not ComplianceReviewFindingType.OBSERVATION:
                raise FindingOperationError("Only an observation can be accepted directly")


@dataclass(frozen=True, slots=True)
class ComplianceReviewDirectFindingTransitions:
    finding_operations: FindingOperationPolicy = field(
        default_factory=ComplianceReviewFindingOperations
    )
    finding_workflow: FindingWorkflowPolicy = field(
        default_factory=ComplianceReviewFindingWorkflow
    )

    def decide(
        self,
        action: str,
        context: FindingOperationContext,
    ) -> DirectFindingTransitionDecision:
        try:
            operation = ComplianceReviewFindingAction(action)
        except ValueError as exc:
            raise FindingOperationError(f"Unknown Finding action: {action!r}") from exc
        if operation not in {
            ComplianceReviewFindingAction.ISSUE,
            ComplianceReviewFindingAction.ACCEPT_OBSERVATION,
            ComplianceReviewFindingAction.VOID,
        }:
            raise FindingOperationError(
                f"Finding action {action!r} is not a direct compliance transition"
            )
        self.finding_operations.validate_transition(action, context)
        lifecycle = context.current_finding_lifecycle
        if lifecycle is None:
            raise FindingOperationError("Finding transition requires a current lifecycle")
        target = self.finding_workflow.transition(
            lifecycle,
            action,
            FindingTransitionContext(
                reason=context.reason,
                non_cancelled_action_count=context.non_cancelled_action_count,
                all_non_cancelled_actions_done=context.all_non_cancelled_actions_done,
            ),
        )
        required_permission = (
            ComplianceReviewPermission.ACCEPT_OBSERVATION
            if operation is ComplianceReviewFindingAction.ACCEPT_OBSERVATION
            else ComplianceReviewPermission.ISSUE_FINDING
        )
        return DirectFindingTransitionDecision(
            required_permission=required_permission,
            target_lifecycle=target,
        )


@dataclass(frozen=True, slots=True)
class ComplianceReviewActionWorkflow:
    def transition(
        self,
        lifecycle: ActionItemLifecycle,
        action: str,
        context: ActionItemTransitionContext,
    ) -> ActionItemLifecycle:
        try:
            operation = ComplianceReviewActionItemAction(action)
        except ValueError as exc:
            raise WorkflowTransitionError(f"Unknown ActionItem action: {action!r}") from exc
        if (
            lifecycle is ActionItemLifecycle.TODO
            and operation is ComplianceReviewActionItemAction.START
        ):
            return ActionItemLifecycle.IN_PROGRESS
        if (
            lifecycle is ActionItemLifecycle.IN_PROGRESS
            and operation is ComplianceReviewActionItemAction.COMPLETE
        ):
            return ActionItemLifecycle.DONE
        if operation is ComplianceReviewActionItemAction.CANCEL and lifecycle in {
            ActionItemLifecycle.TODO,
            ActionItemLifecycle.IN_PROGRESS,
        }:
            if not _has_reason(context.reason):
                raise WorkflowTransitionError("Cancelling an ActionItem requires a reason")
            return ActionItemLifecycle.CANCELLED
        if (
            lifecycle is ActionItemLifecycle.DONE
            and operation is ComplianceReviewActionItemAction.REOPEN
        ):
            return ActionItemLifecycle.IN_PROGRESS
        raise WorkflowTransitionError(
            f"ActionItem cannot perform {operation.value!r} from lifecycle {lifecycle.value!r}"
        )


@dataclass(frozen=True, slots=True)
class ComplianceReviewActionOperations:
    @staticmethod
    def _require_active_rectification(context: ActionItemOperationContext) -> None:
        if context.case_lifecycle not in _ACTIVE_CASE_LIFECYCLES:
            raise ActionItemOperationError("Compliance rectification requires an active ReviewCase")
        if context.finding_lifecycle is not FindingLifecycle.RECTIFYING:
            raise ActionItemOperationError(
                "Compliance ActionItem operations require a rectifying Finding"
            )

    def validate_create(self, context: ActionItemOperationContext) -> None:
        self._require_active_rectification(context)
        if context.current_action_lifecycle is not None:
            raise ActionItemOperationError("ActionItem creation requires no current ActionItem")

    def validate_assignee_management(self, context: ActionItemOperationContext) -> None:
        self._require_active_rectification(context)
        if context.current_action_lifecycle not in {
            ActionItemLifecycle.TODO,
            ActionItemLifecycle.IN_PROGRESS,
        }:
            raise ActionItemOperationError(
                "ActionItem assignees can only be changed before the ActionItem is terminal"
            )

    def validate_transition(self, action: str, context: ActionItemOperationContext) -> None:
        self._require_active_rectification(context)
        if context.current_action_lifecycle is None:
            raise ActionItemOperationError("ActionItem transition requires a current ActionItem")
        try:
            ComplianceReviewActionItemAction(action)
        except ValueError as exc:
            raise ActionItemOperationError(f"Unknown ActionItem action: {action!r}") from exc

    def validate_evidence_registration(self, context: ActionItemOperationContext) -> None:
        self._require_active_rectification(context)
        if context.current_action_lifecycle not in {
            ActionItemLifecycle.TODO,
            ActionItemLifecycle.IN_PROGRESS,
            ActionItemLifecycle.DONE,
        }:
            raise ActionItemOperationError(
                "Evidence cannot be registered for a cancelled ActionItem"
            )


@dataclass(frozen=True, slots=True)
class ComplianceReviewAuthorizationPolicy:
    def allows(self, permission: str, context: AuthorizationContext) -> bool:
        try:
            requested = ComplianceReviewPermission(permission)
        except ValueError:
            return False
        case_roles = _direct_user_role_keys(context.case_role_grants)
        finding_roles = _direct_user_role_keys(context.finding_role_grants)
        department_finding_roles = _department_member_role_keys(context.finding_role_grants)
        action_roles = _direct_user_role_keys(context.action_role_grants)

        if requested is ComplianceReviewPermission.CREATE_CASE:
            return context.is_active_organization_user
        if requested in {
            ComplianceReviewPermission.VIEW_CASE,
            ComplianceReviewPermission.VIEW_FINDING,
        }:
            return bool(
                case_roles.intersection({"lead", "auditor", "reviewer", "observer"})
                or finding_roles.intersection({"owner", "collaborator"})
                or "responsible_department" in department_finding_roles
                or action_roles.intersection({"primary", "collaborator"})
            )
        if requested in {
            ComplianceReviewPermission.MANAGE_CASE_MEMBERS,
            ComplianceReviewPermission.TRANSITION_CASE,
        }:
            return "lead" in case_roles
        if requested in {
            ComplianceReviewPermission.CREATE_FINDING,
            ComplianceReviewPermission.ISSUE_FINDING,
            ComplianceReviewPermission.MANAGE_FINDING_PARTICIPANTS,
        }:
            return bool(case_roles.intersection({"lead", "auditor"}))
        if requested is ComplianceReviewPermission.ACCEPT_OBSERVATION:
            return "reviewer" in case_roles
        if requested in {
            ComplianceReviewPermission.CREATE_ACTION,
            ComplianceReviewPermission.MANAGE_ACTION_ASSIGNEES,
            ComplianceReviewPermission.SUBMIT_RECTIFICATION,
        }:
            return "owner" in finding_roles
        if requested is ComplianceReviewPermission.UPDATE_ASSIGNED_ACTION:
            return bool(action_roles.intersection({"primary", "collaborator"}))
        if requested is ComplianceReviewPermission.ADD_RECTIFICATION_EVIDENCE:
            return "owner" in finding_roles or bool(
                action_roles.intersection({"primary", "collaborator"})
            )
        if requested is ComplianceReviewPermission.VERIFY_FINDING:
            return "reviewer" in case_roles
        if requested is ComplianceReviewPermission.REOPEN_FINDING:
            return bool(case_roles.intersection({"lead", "auditor", "reviewer"}))
        return False


@dataclass(frozen=True, slots=True)
class ComplianceReviewCollaborationRecipientPolicy(CollaborationRecipientPolicy):
    authorization: AuthorizationPolicy = field(default_factory=ComplianceReviewAuthorizationPolicy)

    def is_recipient(
        self,
        intent: CollaborationRecipientIntent,
        context: AuthorizationContext,
    ) -> bool:
        permission_by_intent = {
            CollaborationRecipientIntent.FINDING_RECTIFICATION: (
                ComplianceReviewPermission.SUBMIT_RECTIFICATION
            ),
            CollaborationRecipientIntent.ACTION_EXECUTION: (
                ComplianceReviewPermission.UPDATE_ASSIGNED_ACTION
            ),
            CollaborationRecipientIntent.CASE_DEADLINE: (
                ComplianceReviewPermission.TRANSITION_CASE
            ),
        }
        return self.authorization.allows(permission_by_intent[intent], context)


@dataclass(frozen=True, slots=True)
class ComplianceReviewSubmissionPolicy:
    finding_workflow: FindingWorkflowPolicy = field(
        default_factory=ComplianceReviewFindingWorkflow
    )

    def decide(self, request: SubmissionRequest) -> SubmissionDecision:
        try:
            operation = ComplianceReviewSubmissionAction(request.action)
        except ValueError as exc:
            raise SubmissionDecisionError(
                f"Unknown Compliance Review submission action: {request.action!r}"
            ) from exc

        if operation is ComplianceReviewSubmissionAction.SUBMIT_PLAN:
            self._require_rectification_stage(request, "plan")
            if request.current_lifecycle is not FindingLifecycle.RECTIFYING:
                raise SubmissionDecisionError(
                    "Rectification plan can only be submitted while Finding is rectifying"
                )
            _raise_submission_errors(_required_text_fields(request.payload, ("root_cause",)))
            return SubmissionDecision(
                required_permission=ComplianceReviewPermission.SUBMIT_RECTIFICATION,
                target_lifecycle=FindingLifecycle.RECTIFYING,
                activity_event_type="finding.rectification_plan_submitted",
            )

        if operation is ComplianceReviewSubmissionAction.SUBMIT_FOR_VERIFICATION:
            self._require_rectification_stage(request, "completion")
            _raise_submission_errors(_required_text_fields(request.payload, ("comment",)))
            target = self.finding_workflow.transition(
                request.current_lifecycle,
                ComplianceReviewFindingAction.SUBMIT_FOR_VERIFICATION,
                request.transition_context,
            )
            return SubmissionDecision(
                required_permission=ComplianceReviewPermission.SUBMIT_RECTIFICATION,
                target_lifecycle=target,
                activity_event_type="finding.submitted_for_verification",
            )

        if operation is ComplianceReviewSubmissionAction.APPROVE:
            self._require_verification_result(request, "approved")
            target = self.finding_workflow.transition(
                request.current_lifecycle,
                ComplianceReviewFindingAction.APPROVE,
                FindingTransitionContext(),
            )
            return SubmissionDecision(
                required_permission=ComplianceReviewPermission.VERIFY_FINDING,
                target_lifecycle=target,
                activity_event_type="finding.approved",
            )

        self._require_verification_result(request, "rejected")
        _raise_submission_errors(_required_text_fields(request.payload, ("comment",)))
        comment = request.payload["comment"]
        assert isinstance(comment, str)
        target = self.finding_workflow.transition(
            request.current_lifecycle,
            ComplianceReviewFindingAction.REJECT,
            FindingTransitionContext(reason=comment),
        )
        return SubmissionDecision(
            required_permission=ComplianceReviewPermission.VERIFY_FINDING,
            target_lifecycle=target,
            activity_event_type="finding.rejected",
        )

    @staticmethod
    def _require_rectification_stage(request: SubmissionRequest, stage: str) -> None:
        if request.purpose is not SubmissionPurpose.RECTIFICATION:
            raise SubmissionDecisionError(
                f"{request.action} requires rectification Submission purpose"
            )
        if request.payload.get("stage") != stage:
            raise SubmissionDecisionError(
                f"{request.action} requires rectification stage {stage!r}"
            )

    @staticmethod
    def _require_verification_result(request: SubmissionRequest, result: str) -> None:
        if request.purpose is not SubmissionPurpose.VERIFICATION:
            raise SubmissionDecisionError(
                f"{request.action} requires verification Submission purpose"
            )
        if request.payload.get("result") != result:
            raise SubmissionDecisionError(
                f"{request.action} requires verification result {result!r}"
            )


@dataclass(frozen=True, slots=True)
class ComplianceReviewV1Policy:
    scenario: Scenario = field(
        default_factory=lambda: Scenario(
            key=ScenarioKey("compliance_review"),
            version=ScenarioVersion(1),
            name="Compliance Review",
        )
    )
    case_role_specs: tuple[RoleSpecification, ...] = COMPLIANCE_REVIEW_CASE_ROLE_SPECS
    finding_participant_role_specs: tuple[RoleSpecification, ...] = (
        COMPLIANCE_REVIEW_FINDING_ROLE_SPECS
    )
    action_assignee_role_specs: tuple[RoleSpecification, ...] = (
        COMPLIANCE_REVIEW_ACTION_ROLE_SPECS
    )
    case_creation: ReviewCaseCreationPolicy = field(
        default_factory=ComplianceReviewCaseCreationPolicy
    )
    case_workflow: ReviewCaseWorkflowPolicy = field(default_factory=ComplianceReviewCaseWorkflow)
    finding_workflow: FindingWorkflowPolicy = field(default_factory=ComplianceReviewFindingWorkflow)
    finding_operations: FindingOperationPolicy = field(
        default_factory=ComplianceReviewFindingOperations
    )
    finding_direct_transitions: DirectFindingTransitionPolicy = field(
        default_factory=ComplianceReviewDirectFindingTransitions
    )
    action_workflow: ActionItemWorkflowPolicy = field(
        default_factory=ComplianceReviewActionWorkflow
    )
    action_operations: ActionItemOperationPolicy = field(
        default_factory=ComplianceReviewActionOperations
    )
    authorization: AuthorizationPolicy = field(default_factory=ComplianceReviewAuthorizationPolicy)
    collaboration_recipients: CollaborationRecipientPolicy = field(
        default_factory=ComplianceReviewCollaborationRecipientPolicy
    )
    submission_policy: SubmissionPolicy = field(default_factory=ComplianceReviewSubmissionPolicy)

    def validate_case_input(self, payload: Mapping[str, object]) -> tuple[str, ...]:
        return _required_text_fields(payload, ("standard_reference", "scope_summary"))

    def validate_finding_input(self, payload: Mapping[str, object]) -> tuple[str, ...]:
        errors = list(_required_text_fields(payload, ("criterion_reference", "finding_type")))
        finding_type = payload.get("finding_type")
        if (
            isinstance(finding_type, str)
            and finding_type.strip()
            and finding_type == finding_type.strip()
        ):
            try:
                ComplianceReviewFindingType(finding_type)
            except ValueError:
                errors.append("finding_type must be 'nonconformity' or 'observation'")
        return tuple(errors)


COMPLIANCE_REVIEW_V1 = ComplianceReviewV1Policy()
