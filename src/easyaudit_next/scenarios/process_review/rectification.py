from dataclasses import dataclass, field
from enum import StrEnum

from easyaudit_next.review_core.domain.models import (
    ActionItemLifecycle,
    FindingLifecycle,
    ReviewCaseLifecycle,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActionItemOperationContext,
    ActionItemOperationError,
    ActionItemOperationPolicy,
    ActorKind,
    AuthorizationContext,
    AuthorizationPolicy,
    PermissionSource,
)
from easyaudit_next.scenarios.process_review.v1 import (
    ProcessReviewActionItemAction,
    ProcessReviewAuthorizationPolicy,
    ProcessReviewV1BasePolicy,
)


class ProcessReviewRectificationPermission(StrEnum):
    MANAGE_ACTION_ASSIGNEES = "manage_action_assignees"
    ADD_RECTIFICATION_EVIDENCE = "add_rectification_evidence"


_ACTIVE_CASE_LIFECYCLES = {
    ReviewCaseLifecycle.IN_PROGRESS,
    ReviewCaseLifecycle.AWAITING_CLOSURE,
}


def _direct_user_role_keys(context: AuthorizationContext, *, action: bool) -> frozenset[str]:
    grants = context.action_role_grants if action else context.finding_role_grants
    return frozenset(
        grant.role_key
        for grant in grants
        if grant.actor_kind is ActorKind.USER
        and grant.source is PermissionSource.DIRECT
    )


@dataclass(frozen=True, slots=True)
class ProcessReviewActionOperations:
    """Process Review v1 invariants for rectification operations."""

    @staticmethod
    def _require_active_rectification(context: ActionItemOperationContext) -> None:
        if context.case_lifecycle not in _ACTIVE_CASE_LIFECYCLES:
            raise ActionItemOperationError(
                "Process Review rectification requires an active ReviewCase"
            )
        if context.finding_lifecycle is not FindingLifecycle.RECTIFYING:
            raise ActionItemOperationError(
                "Process Review ActionItem operations require a rectifying Finding"
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

    def validate_transition(
        self,
        action: str,
        context: ActionItemOperationContext,
    ) -> None:
        self._require_active_rectification(context)
        if context.current_action_lifecycle is None:
            raise ActionItemOperationError("ActionItem transition requires a current ActionItem")
        try:
            ProcessReviewActionItemAction(action)
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
class ProcessReviewRectificationAuthorizationPolicy(ProcessReviewAuthorizationPolicy):
    def allows(self, permission: str, context: AuthorizationContext) -> bool:
        finding_roles = _direct_user_role_keys(context, action=False)
        action_roles = _direct_user_role_keys(context, action=True)
        if permission == ProcessReviewRectificationPermission.MANAGE_ACTION_ASSIGNEES:
            return "owner" in finding_roles
        if permission == ProcessReviewRectificationPermission.ADD_RECTIFICATION_EVIDENCE:
            return "owner" in finding_roles or bool(
                action_roles.intersection({"primary", "collaborator"})
            )
        return ProcessReviewAuthorizationPolicy.allows(self, permission, context)


@dataclass(frozen=True, slots=True)
class ProcessReviewV1Policy(ProcessReviewV1BasePolicy):
    """The single complete immutable policy registered for process_review@1."""

    action_operations: ActionItemOperationPolicy = field(
        default_factory=ProcessReviewActionOperations
    )
    authorization: AuthorizationPolicy = field(
        default_factory=ProcessReviewRectificationAuthorizationPolicy
    )


PROCESS_REVIEW_V1 = ProcessReviewV1Policy()
