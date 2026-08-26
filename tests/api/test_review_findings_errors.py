import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from easyaudit_next.api.review_findings import _raise_api_error
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
)
from easyaudit_next.review_core.application.review_planning import ReviewAuthorizationError
from easyaudit_next.review_core.domain.scenario_capabilities import FindingOperationError


@pytest.mark.parametrize(
    ("exc", "expected_status"),
    [
        (ReviewAuthorizationError("forbidden"), 403),
        (LookupError("missing"), 404),
        (ValueError("invalid scenario data"), 422),
        (FindingOperationError("invalid finding operation"), 422),
        (ConcurrentFindingTransitionError("Concurrent Finding transition"), 409),
        (IntegrityError("statement", {}, Exception("constraint")), 409),
    ],
)
def test_finding_api_error_semantics(exc: Exception, expected_status: int) -> None:
    with pytest.raises(HTTPException) as caught:
        _raise_api_error(exc)

    assert caught.value.status_code == expected_status
