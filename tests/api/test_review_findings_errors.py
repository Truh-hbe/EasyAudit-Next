from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

import easyaudit_next.api.review_findings as review_findings_api
from easyaudit_next.api.review_contracts import FindingCreateRequest
from easyaudit_next.api.review_findings import _raise_api_error, create_finding
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
)
from easyaudit_next.review_core.application.review_planning import (
    ConcurrentCaseTransitionError,
    ReviewAuthorizationError,
)
from easyaudit_next.review_core.domain.models import FindingSeverity
from easyaudit_next.review_core.domain.scenario_capabilities import FindingOperationError
from easyaudit_next.rules import RuleCode


@pytest.mark.parametrize(
    ("exc", "expected_status"),
    [
        (ReviewAuthorizationError("forbidden"), 403),
        (LookupError("missing"), 404),
        (ValueError("invalid scenario data"), 422),
        (ConcurrentCaseTransitionError("Concurrent ReviewCase transition"), 409),
        (ConcurrentFindingTransitionError("Concurrent Finding transition"), 409),
        (IntegrityError("statement", {}, Exception("constraint")), 409),
    ],
)
def test_finding_api_error_semantics(exc: Exception, expected_status: int) -> None:
    with pytest.raises(HTTPException) as caught:
        _raise_api_error(exc)

    assert caught.value.status_code == expected_status


def test_finding_rule_violation_is_left_to_the_coded_422_handler() -> None:
    violation = FindingOperationError(RuleCode.FINDING_REQUIRES_OPEN, "invalid finding operation")

    with pytest.raises(FindingOperationError) as caught:
        _raise_api_error(violation)

    assert caught.value is violation


class _CaseConflictFindingService:
    def create_finding(self, *args: object, **kwargs: object) -> None:
        raise ConcurrentCaseTransitionError("Concurrent ReviewCase transition")


def test_create_finding_maps_stale_case_conflict_to_http_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        review_findings_api,
        "build_finding_lifecycle_service",
        lambda _: _CaseConflictFindingService(),
    )
    payload = FindingCreateRequest(
        title="Late finding",
        severity=FindingSeverity.MEDIUM,
        scenario_data={},
    )

    with pytest.raises(HTTPException) as caught:
        create_finding(
            uuid4(),
            payload,
            SimpleNamespace(user=object()),
            object(),
        )

    assert caught.value.status_code == 409
    assert caught.value.detail == "Concurrent ReviewCase transition"


@pytest.mark.parametrize(
    "module_name",
    [
        "review_planning",
        "review_verification",
        "review_rectification",
        "review_findings",
    ],
)
def test_review_api_integrity_error_never_leaks_sql_or_parameters(module_name: str) -> None:
    import importlib

    module = importlib.import_module(f"easyaudit_next.api.{module_name}")
    exc = IntegrityError(
        "INSERT INTO findings (password_hash) VALUES (%(password_hash)s)",
        {"password_hash": "SYNTHETIC_HASH_MARKER"},
        Exception("constraint"),
    )

    with pytest.raises(HTTPException) as caught:
        module._raise_api_error(exc)

    assert caught.value.status_code == 409
    detail = str(caught.value.detail)
    for marker in ("INSERT INTO", "SYNTHETIC_HASH_MARKER", "password_hash"):
        assert marker not in detail
