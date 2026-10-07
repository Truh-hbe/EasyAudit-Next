import pytest

from easyaudit_next.review_core.domain.models import ReviewCaseLifecycle
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActorKind,
    AuthorizationContext,
    PermissionSource,
    ReviewCaseTransitionContext,
    RoleGrant,
    WorkflowTransitionError,
)
from easyaudit_next.scenarios.compliance_review import COMPLIANCE_REVIEW_V1
from easyaudit_next.scenarios.process_review import PROCESS_REVIEW_V1

POLICIES = [PROCESS_REVIEW_V1, COMPLIANCE_REVIEW_V1]
IDS = ["process_review", "compliance_review"]


@pytest.mark.parametrize("policy", POLICIES, ids=IDS)
def test_reopen_fieldwork_returns_awaiting_closure_to_in_progress(policy) -> None:  # type: ignore[no-untyped-def]
    target = policy.case_workflow.transition(
        ReviewCaseLifecycle.AWAITING_CLOSURE,
        "reopen_fieldwork",
        ReviewCaseTransitionContext(reason="补录发现项"),
    )
    assert target is ReviewCaseLifecycle.IN_PROGRESS


@pytest.mark.parametrize("policy", POLICIES, ids=IDS)
@pytest.mark.parametrize("reason", [None, "", "  \n"])
def test_reopen_fieldwork_requires_a_non_blank_reason(policy, reason) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(WorkflowTransitionError, match="requires a reason"):
        policy.case_workflow.transition(
            ReviewCaseLifecycle.AWAITING_CLOSURE,
            "reopen_fieldwork",
            ReviewCaseTransitionContext(reason=reason),
        )


@pytest.mark.parametrize("policy", POLICIES, ids=IDS)
@pytest.mark.parametrize(
    "lifecycle",
    [
        ReviewCaseLifecycle.DRAFT,
        ReviewCaseLifecycle.SCHEDULED,
        ReviewCaseLifecycle.IN_PROGRESS,
        ReviewCaseLifecycle.CLOSED,
        ReviewCaseLifecycle.CANCELLED,
    ],
)
def test_reopen_fieldwork_is_only_valid_from_awaiting_closure(policy, lifecycle) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(WorkflowTransitionError):
        policy.case_workflow.transition(
            lifecycle, "reopen_fieldwork", ReviewCaseTransitionContext(reason="x")
        )


@pytest.mark.parametrize("policy", POLICIES, ids=IDS)
def test_closing_still_requires_terminal_findings_after_a_reopen(policy) -> None:  # type: ignore[no-untyped-def]
    workflow = policy.case_workflow
    awaiting = workflow.transition(
        workflow.transition(
            ReviewCaseLifecycle.AWAITING_CLOSURE,
            "reopen_fieldwork",
            ReviewCaseTransitionContext(reason="x"),
        ),
        "finish_fieldwork",
        ReviewCaseTransitionContext(),
    )
    assert awaiting is ReviewCaseLifecycle.AWAITING_CLOSURE
    with pytest.raises(WorkflowTransitionError, match="every Finding"):
        workflow.transition(awaiting, "close", ReviewCaseTransitionContext())


@pytest.mark.parametrize("policy", POLICIES, ids=IDS)
def test_transition_permission_is_scenario_authorization_not_a_role_name(policy) -> None:  # type: ignore[no-untyped-def]
    def context(role: str) -> AuthorizationContext:
        return AuthorizationContext(
            is_active_organization_user=True,
            case_role_grants=frozenset({RoleGrant(role, ActorKind.USER, PermissionSource.DIRECT)}),
        )

    # 恢复现场与完成现场工作共用同一个能力：授权由场景决定。
    assert policy.authorization.allows("transition_case", context("lead"))
    for role in ("auditor", "reviewer", "observer"):
        assert not policy.authorization.allows("transition_case", context(role))
