from dataclasses import dataclass, field

from easyaudit_next.review_core.domain.scenario_capabilities import (
    DirectFindingTransitionDecision,
    FindingOperationContext,
    FindingOperationError,
    FindingOperationPolicy,
    FindingTransitionContext,
    FindingWorkflowPolicy,
)
from easyaudit_next.scenarios.process_review.v1 import (
    ProcessReviewFindingAction,
    ProcessReviewFindingOperations,
    ProcessReviewFindingWorkflow,
    ProcessReviewPermission,
)


@dataclass(frozen=True, slots=True)
class ProcessReviewDirectFindingTransitions:
    """Scenario-owned commands exposed through the generic direct transition surface."""

    finding_operations: FindingOperationPolicy = field(
        default_factory=ProcessReviewFindingOperations
    )
    finding_workflow: FindingWorkflowPolicy = field(
        default_factory=ProcessReviewFindingWorkflow
    )

    def decide(
        self,
        action: str,
        context: FindingOperationContext,
    ) -> DirectFindingTransitionDecision:
        try:
            operation = ProcessReviewFindingAction(action)
        except ValueError as exc:
            raise FindingOperationError(f"Unknown Finding action: {action!r}") from exc
        if operation not in {
            ProcessReviewFindingAction.ISSUE,
            ProcessReviewFindingAction.VOID,
        }:
            raise FindingOperationError(
                "M2.3 only supports issuing or voiding an open Finding"
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
        return DirectFindingTransitionDecision(
            required_permission=ProcessReviewPermission.ISSUE_FINDING,
            target_lifecycle=target,
        )
