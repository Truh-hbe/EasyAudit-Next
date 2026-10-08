import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from easyaudit_next.api.review_rectification import _raise_api_error
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
)
from easyaudit_next.review_core.application.review_planning import (
    ConcurrentCaseTransitionError,
    ReviewAuthorizationError,
)
from easyaudit_next.review_core.application.review_rectification import (
    ConcurrentActionItemTransitionError,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActionItemOperationError,
    SubmissionDecisionError,
    WorkflowTransitionError,
)
from easyaudit_next.rules import RuleCode


@pytest.mark.parametrize(
    "violation",
    [
        ActionItemOperationError(RuleCode.ACTION_MISSING, "invalid action operation"),
        WorkflowTransitionError(RuleCode.WORKFLOW_UNKNOWN_ACTION, "invalid action transition"),
        SubmissionDecisionError(RuleCode.SUBMISSION_MISMATCH, "invalid submission"),
    ],
)
def test_rectification_rule_violations_are_left_to_the_coded_422_handler(
    violation: Exception,
) -> None:
    with pytest.raises(type(violation)) as caught:
        _raise_api_error(violation)

    assert caught.value is violation


@pytest.mark.parametrize(
    ("exc", "expected_status"),
    [
        (ReviewAuthorizationError("forbidden"), 403),
        (LookupError("missing"), 404),
        (ValueError("invalid rectification input"), 422),
        (ConcurrentActionItemTransitionError("Concurrent ActionItem transition"), 409),
        (ConcurrentCaseTransitionError("Concurrent ReviewCase transition"), 409),
        (ConcurrentFindingTransitionError("Concurrent Finding transition"), 409),
        (IntegrityError("statement", {}, Exception("constraint")), 409),
    ],
)
def test_rectification_api_error_semantics(exc: Exception, expected_status: int) -> None:
    with pytest.raises(HTTPException) as caught:
        _raise_api_error(exc)

    assert caught.value.status_code == expected_status
