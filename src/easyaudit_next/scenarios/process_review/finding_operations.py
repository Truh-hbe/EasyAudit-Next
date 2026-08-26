from dataclasses import dataclass, field

from easyaudit_next.review_core.domain.models import FindingLifecycle, ReviewCaseLifecycle
from easyaudit_next.review_core.domain.scenario_capabilities import (
    FindingOperationContext,
    FindingOperationError,
    FindingOperationPolicy,
)
from easyaudit_next.scenarios.process_review.v1 import (
    ProcessReviewFindingAction,
    ProcessReviewV1Policy,
)


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
            raise FindingOperationError(
                "Process Review issue/void requires an open Finding"
            )
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
class ProcessReviewV1PolicyWithFindingOperations(ProcessReviewV1Policy):
    finding_operations: FindingOperationPolicy = field(
        default_factory=ProcessReviewFindingOperations
    )


PROCESS_REVIEW_V1_WITH_FINDING_OPERATIONS = ProcessReviewV1PolicyWithFindingOperations()
