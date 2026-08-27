import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from easyaudit_next.api.review_planning import _raise_api_error as raise_planning_error
from easyaudit_next.api.review_verification import _raise_api_error as raise_verification_error
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
)
from easyaudit_next.review_core.application.review_planning import (
    ConcurrentCaseTransitionError,
    ReviewAuthorizationError,
)


@pytest.mark.parametrize(
    ("exc", "expected_status"),
    [
        (ReviewAuthorizationError("forbidden"), 403),
        (LookupError("missing"), 404),
        (ValueError("invalid verification input"), 422),
        (ConcurrentCaseTransitionError("Concurrent ReviewCase transition"), 409),
        (ConcurrentFindingTransitionError("Concurrent Finding transition"), 409),
        (IntegrityError("statement", {}, Exception("constraint")), 409),
    ],
)
def test_verification_api_error_semantics(exc: Exception, expected_status: int) -> None:
    with pytest.raises(HTTPException) as caught:
        raise_verification_error(exc)

    assert caught.value.status_code == expected_status


def test_case_closure_business_validation_is_422_not_concurrency() -> None:
    with pytest.raises(HTTPException) as caught:
        raise_planning_error(ValueError("ReviewCase requires terminal Findings"))

    assert caught.value.status_code == 422


def test_case_concurrency_remains_409() -> None:
    with pytest.raises(HTTPException) as caught:
        raise_planning_error(ConcurrentCaseTransitionError("Concurrent ReviewCase transition"))

    assert caught.value.status_code == 409
