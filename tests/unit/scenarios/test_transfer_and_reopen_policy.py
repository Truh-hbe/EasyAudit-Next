import pytest

from easyaudit_next.review_core.domain.models import (
    ActionItemLifecycle,
    FindingLifecycle,
    ReviewCaseLifecycle,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActionItemOperationContext,
    ActionItemOperationError,
    ActionItemTransitionContext,
    ActorKind,
    AuthorizationContext,
    PermissionSource,
    RoleGrant,
)
from easyaudit_next.scenarios.compliance_review import COMPLIANCE_REVIEW_V1
from easyaudit_next.scenarios.process_review import PROCESS_REVIEW_V1

PERMISSION = "transfer_and_reopen_action"
POLICIES = [PROCESS_REVIEW_V1, COMPLIANCE_REVIEW_V1]


def _grant(role_key: str, kind: ActorKind = ActorKind.USER) -> RoleGrant:
    source = (
        PermissionSource.DIRECT
        if kind is ActorKind.USER
        else PermissionSource.DEPARTMENT_MEMBERSHIP
    )
    return RoleGrant(role_key, kind, source)


def _context(
    *,
    case: ReviewCaseLifecycle = ReviewCaseLifecycle.IN_PROGRESS,
    finding: FindingLifecycle = FindingLifecycle.RECTIFYING,
    action: ActionItemLifecycle | None = ActionItemLifecycle.DONE,
    reason: str | None = "executor left the company",
    active_executor: bool = False,
) -> ActionItemOperationContext:
    return ActionItemOperationContext(
        case_lifecycle=case,
        finding_lifecycle=finding,
        current_action_lifecycle=action,
        has_active_assignee=active_executor,
        reason=reason,
    )


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: p.scenario.key)
def test_done_action_in_rectifying_finding_reopens_to_the_scenario_reopen_target(policy) -> None:
    reopen = policy.action_operations.decide_transfer_and_reopen(_context())

    target = policy.action_workflow.transition(
        ActionItemLifecycle.DONE,
        reopen,
        ActionItemTransitionContext(reason="executor left the company"),
    )
    assert target is ActionItemLifecycle.IN_PROGRESS


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: p.scenario.key)
def test_awaiting_closure_case_still_allows_the_command(policy) -> None:
    policy.action_operations.decide_transfer_and_reopen(
        _context(case=ReviewCaseLifecycle.AWAITING_CLOSURE)
    )


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: p.scenario.key)
@pytest.mark.parametrize(
    "action",
    [
        ActionItemLifecycle.TODO,
        ActionItemLifecycle.IN_PROGRESS,
        ActionItemLifecycle.CANCELLED,
        None,
    ],
)
def test_only_a_done_action_can_be_transferred(policy, action) -> None:
    with pytest.raises(ActionItemOperationError, match="done ActionItem"):
        policy.action_operations.decide_transfer_and_reopen(_context(action=action))


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: p.scenario.key)
@pytest.mark.parametrize(
    "finding",
    [
        FindingLifecycle.OPEN,
        FindingLifecycle.VERIFYING,
        FindingLifecycle.CLOSED,
        FindingLifecycle.VOIDED,
    ],
)
def test_finding_must_be_rectifying(policy, finding) -> None:
    with pytest.raises(ActionItemOperationError, match="rectifying Finding"):
        policy.action_operations.decide_transfer_and_reopen(_context(finding=finding))


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: p.scenario.key)
@pytest.mark.parametrize(
    "case",
    [ReviewCaseLifecycle.DRAFT, ReviewCaseLifecycle.CLOSED, ReviewCaseLifecycle.CANCELLED],
)
def test_case_must_be_active(policy, case) -> None:
    with pytest.raises(ActionItemOperationError, match="active ReviewCase"):
        policy.action_operations.decide_transfer_and_reopen(_context(case=case))


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: p.scenario.key)
@pytest.mark.parametrize("reason", [None, "", "   "])
def test_reason_is_required(policy, reason) -> None:
    with pytest.raises(ActionItemOperationError, match="requires a reason"):
        policy.action_operations.decide_transfer_and_reopen(_context(reason=reason))


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: p.scenario.key)
def test_permission_belongs_to_the_finding_owner_only(policy) -> None:
    authorization = policy.authorization

    assert authorization.allows(
        PERMISSION, AuthorizationContext(finding_role_grants=frozenset({_grant("owner")}))
    )
    for denied in (
        AuthorizationContext(finding_role_grants=frozenset({_grant("collaborator")})),
        AuthorizationContext(action_role_grants=frozenset({_grant("primary")})),
        AuthorizationContext(action_role_grants=frozenset({_grant("collaborator")})),
        AuthorizationContext(
            case_role_grants=frozenset(
                _grant(role) for role in ("lead", "auditor", "reviewer", "observer")
            )
        ),
        AuthorizationContext(
            finding_role_grants=frozenset(
                {_grant("responsible_department", ActorKind.DEPARTMENT)}
            )
        ),
        # platform system_admin has no business facts, hence no grants at all
        AuthorizationContext(is_active_organization_user=True),
    ):
        assert not authorization.allows(PERMISSION, denied)


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: p.scenario.key)
def test_an_active_executor_blocks_the_command_and_the_state_check(policy) -> None:
    for method in (
        policy.action_operations.decide_transfer_and_reopen,
        policy.action_operations.validate_transfer_and_reopen_state,
    ):
        with pytest.raises(ActionItemOperationError, match="active executor"):
            method(_context(active_executor=True))


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: p.scenario.key)
def test_state_check_needs_no_reason_but_the_command_does(policy) -> None:
    policy.action_operations.validate_transfer_and_reopen_state(_context(reason=None))
    with pytest.raises(ActionItemOperationError, match="requires a reason"):
        policy.action_operations.decide_transfer_and_reopen(_context(reason=None))
