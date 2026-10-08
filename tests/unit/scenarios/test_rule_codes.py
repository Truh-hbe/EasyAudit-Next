"""Scenario rule violations carry stable codes and parameters (the web client maps them)."""

import pytest

from easyaudit_next.review_core.domain.models import (
    FindingLifecycle,
    ReviewCaseLifecycle,
    SubmissionPurpose,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    FindingOperationContext,
    FindingTransitionContext,
    ReviewCaseTransitionContext,
    SubmissionRequest,
)
from easyaudit_next.rules import FieldErrorCode, RuleCode, RuleViolation
from easyaudit_next.scenarios.compliance_review import COMPLIANCE_REVIEW_V1
from easyaudit_next.scenarios.process_review import PROCESS_REVIEW_V1

POLICIES = [PROCESS_REVIEW_V1, COMPLIANCE_REVIEW_V1]


def _ids(policy: object) -> str:
    return policy.scenario.key  # type: ignore[attr-defined,no-any-return]


def _issue_context(policy: object, roles: frozenset[str]) -> FindingOperationContext:
    data: dict[str, object] = (
        {"finding_type": "nonconformity"} if policy is COMPLIANCE_REVIEW_V1 else {}
    )
    return FindingOperationContext(
        case_lifecycle=ReviewCaseLifecycle.IN_PROGRESS,
        current_finding_lifecycle=FindingLifecycle.OPEN,
        scenario_data=data,
        participant_role_keys=roles,
    )


@pytest.mark.parametrize("policy", POLICIES, ids=_ids)
@pytest.mark.parametrize(
    ("present", "missing"),
    [
        (frozenset(), ("responsible_department", "owner")),
        (frozenset({"owner"}), ("responsible_department",)),
        (frozenset({"responsible_department"}), ("owner",)),
    ],
)
def test_issuing_without_participants_reports_the_missing_role_keys(
    policy, present, missing
) -> None:
    with pytest.raises(RuleViolation) as raised:
        policy.finding_operations.validate_transition("issue", _issue_context(policy, present))

    assert raised.value.code is RuleCode.FINDING_MISSING_PARTICIPANT_ROLES
    assert raised.value.params == {"roles": missing}
    assert "requires participant role(s)" in str(raised.value)


@pytest.mark.parametrize("policy", POLICIES, ids=_ids)
def test_closing_with_open_findings_has_a_code(policy) -> None:
    with pytest.raises(RuleViolation) as raised:
        policy.case_workflow.transition(
            ReviewCaseLifecycle.AWAITING_CLOSURE,
            "close",
            ReviewCaseTransitionContext(all_findings_terminal=False),
        )

    assert raised.value.code is RuleCode.CASE_CLOSE_BLOCKED_BY_OPEN_FINDINGS


@pytest.mark.parametrize("policy", POLICIES, ids=_ids)
@pytest.mark.parametrize(
    ("count", "done", "code"),
    [
        (0, False, RuleCode.FINDING_VERIFICATION_REQUIRES_ACTIONS),
        (2, False, RuleCode.FINDING_VERIFICATION_REQUIRES_ACTIONS_DONE),
    ],
)
def test_verification_preconditions_have_codes(policy, count, done, code) -> None:
    with pytest.raises(RuleViolation) as raised:
        policy.finding_workflow.transition(
            FindingLifecycle.RECTIFYING,
            "submit_for_verification",
            FindingTransitionContext(
                non_cancelled_action_count=count, all_non_cancelled_actions_done=done
            ),
        )

    assert raised.value.code is code


@pytest.mark.parametrize("policy", POLICIES, ids=_ids)
def test_a_missing_reason_is_a_field_error_on_reason(policy) -> None:
    with pytest.raises(RuleViolation) as raised:
        policy.finding_workflow.transition(
            FindingLifecycle.OPEN, "void", FindingTransitionContext(reason="  ")
        )

    assert raised.value.code is RuleCode.REQUEST_INVALID
    assert [(e.field, e.code) for e in raised.value.errors] == [
        ("reason", FieldErrorCode.REQUIRED)
    ]


@pytest.mark.parametrize("policy", POLICIES, ids=_ids)
def test_invalid_and_unknown_transitions_report_entity_action_and_lifecycle(policy) -> None:
    with pytest.raises(RuleViolation) as invalid:
        policy.case_workflow.transition(
            ReviewCaseLifecycle.CLOSED, "start", ReviewCaseTransitionContext()
        )
    assert invalid.value.code is RuleCode.WORKFLOW_INVALID_TRANSITION
    assert invalid.value.params == {
        "entity": "review_case",
        "action": "start",
        "lifecycle": "closed",
    }

    with pytest.raises(RuleViolation) as unknown:
        policy.finding_workflow.transition(
            FindingLifecycle.OPEN, "explode", FindingTransitionContext()
        )
    assert unknown.value.code is RuleCode.WORKFLOW_UNKNOWN_ACTION
    assert unknown.value.params == {"entity": "finding", "action": "explode"}


def _plan_request(payload: dict[str, object]) -> SubmissionRequest:
    return SubmissionRequest(
        current_lifecycle=FindingLifecycle.RECTIFYING,
        action="submit_plan",
        purpose=SubmissionPurpose.RECTIFICATION,
        payload=payload,
    )


@pytest.mark.parametrize("policy", POLICIES, ids=_ids)
@pytest.mark.parametrize(
    ("root_cause", "field_code"),
    [
        (None, FieldErrorCode.REQUIRED),
        ("", FieldErrorCode.REQUIRED),
        (" cause", FieldErrorCode.PADDED),
    ],
)
def test_submission_payload_errors_are_field_errors(policy, root_cause, field_code) -> None:
    payload: dict[str, object] = {"stage": "plan"}
    if root_cause is not None:
        payload["root_cause"] = root_cause

    with pytest.raises(RuleViolation) as raised:
        policy.submission_policy.decide(_plan_request(payload))

    assert raised.value.code is RuleCode.REQUEST_INVALID
    assert [(e.field, e.code) for e in raised.value.errors] == [("root_cause", field_code)]


@pytest.mark.parametrize("policy", POLICIES, ids=_ids)
def test_submission_stage_mismatch_has_a_code(policy) -> None:
    with pytest.raises(RuleViolation) as raised:
        policy.submission_policy.decide(_plan_request({"stage": "completion", "root_cause": "x"}))

    assert raised.value.code is RuleCode.SUBMISSION_MISMATCH
    assert raised.value.params == {"action": "submit_plan", "aspect": "stage"}


def test_compliance_direct_transition_codes() -> None:
    observation = FindingOperationContext(
        case_lifecycle=ReviewCaseLifecycle.IN_PROGRESS,
        current_finding_lifecycle=FindingLifecycle.OPEN,
        scenario_data={"finding_type": "observation"},
    )
    with pytest.raises(RuleViolation) as issue:
        COMPLIANCE_REVIEW_V1.finding_operations.validate_transition("issue", observation)
    assert issue.value.code is RuleCode.FINDING_ISSUE_REQUIRES_NONCONFORMITY

    nonconformity = FindingOperationContext(
        case_lifecycle=ReviewCaseLifecycle.IN_PROGRESS,
        current_finding_lifecycle=FindingLifecycle.OPEN,
        scenario_data={"finding_type": "nonconformity"},
    )
    with pytest.raises(RuleViolation) as accept:
        COMPLIANCE_REVIEW_V1.finding_operations.validate_transition(
            "accept_observation", nonconformity
        )
    assert accept.value.code is RuleCode.FINDING_ACCEPT_REQUIRES_OBSERVATION
