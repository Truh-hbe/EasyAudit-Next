import pytest

from easyaudit_next.review_core.domain.models import (
    ActionItemLifecycle,
    FindingLifecycle,
    ReviewCaseLifecycle,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActionItemOperationContext,
    ActionItemOperationError,
    ActorKind,
    AuthorizationContext,
    PermissionSource,
    RoleGrant,
)
from easyaudit_next.scenarios.process_review import (
    PROCESS_REVIEW_V1,
    ProcessReviewRectificationPermission,
)


def _direct(role_key: str) -> RoleGrant:
    return RoleGrant(role_key, ActorKind.USER, PermissionSource.DIRECT)


def _context(
    *,
    case_lifecycle: ReviewCaseLifecycle = ReviewCaseLifecycle.IN_PROGRESS,
    finding_lifecycle: FindingLifecycle = FindingLifecycle.RECTIFYING,
    action_lifecycle: ActionItemLifecycle | None = None,
) -> ActionItemOperationContext:
    return ActionItemOperationContext(
        case_lifecycle=case_lifecycle,
        finding_lifecycle=finding_lifecycle,
        current_action_lifecycle=action_lifecycle,
    )


def test_action_creation_is_owned_by_scenario_context_invariants() -> None:
    policy = PROCESS_REVIEW_V1.action_operations

    policy.validate_create(_context())
    policy.validate_create(
        _context(case_lifecycle=ReviewCaseLifecycle.AWAITING_CLOSURE)
    )

    with pytest.raises(ActionItemOperationError, match="rectifying Finding"):
        policy.validate_create(_context(finding_lifecycle=FindingLifecycle.OPEN))
    with pytest.raises(ActionItemOperationError, match="active ReviewCase"):
        policy.validate_create(_context(case_lifecycle=ReviewCaseLifecycle.CLOSED))


def test_assignee_management_freezes_terminal_actions() -> None:
    policy = PROCESS_REVIEW_V1.action_operations

    for lifecycle in (ActionItemLifecycle.TODO, ActionItemLifecycle.IN_PROGRESS):
        policy.validate_assignee_management(_context(action_lifecycle=lifecycle))

    for lifecycle in (ActionItemLifecycle.DONE, ActionItemLifecycle.CANCELLED):
        with pytest.raises(ActionItemOperationError, match="before the ActionItem is terminal"):
            policy.validate_assignee_management(_context(action_lifecycle=lifecycle))


def test_evidence_can_document_done_action_but_not_cancelled_action() -> None:
    policy = PROCESS_REVIEW_V1.action_operations

    policy.validate_evidence_registration(_context(action_lifecycle=ActionItemLifecycle.DONE))
    with pytest.raises(ActionItemOperationError, match="cancelled"):
        policy.validate_evidence_registration(
            _context(action_lifecycle=ActionItemLifecycle.CANCELLED)
        )


def test_rectification_permissions_keep_department_visibility_separate_from_write() -> None:
    authorization = PROCESS_REVIEW_V1.authorization
    owner = AuthorizationContext(finding_role_grants=frozenset({_direct("owner")}))
    primary = AuthorizationContext(action_role_grants=frozenset({_direct("primary")}))
    department = AuthorizationContext(
        finding_role_grants=frozenset(
            {
                RoleGrant(
                    "responsible_department",
                    ActorKind.DEPARTMENT,
                    PermissionSource.DEPARTMENT_MEMBERSHIP,
                )
            }
        )
    )

    assert authorization.allows(
        ProcessReviewRectificationPermission.MANAGE_ACTION_ASSIGNEES,
        owner,
    )
    assert authorization.allows(
        ProcessReviewRectificationPermission.ADD_RECTIFICATION_EVIDENCE,
        owner,
    )
    assert authorization.allows(
        ProcessReviewRectificationPermission.ADD_RECTIFICATION_EVIDENCE,
        primary,
    )
    assert not authorization.allows(
        ProcessReviewRectificationPermission.MANAGE_ACTION_ASSIGNEES,
        department,
    )
    assert not authorization.allows(
        ProcessReviewRectificationPermission.ADD_RECTIFICATION_EVIDENCE,
        department,
    )
