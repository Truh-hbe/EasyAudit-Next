"""One error body for every 422: stable `code`/`params`/`errors`, English `detail` for logs."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from easyaudit_next.api.dependencies import get_database_session, require_business_identity
from easyaudit_next.api.errors import CodedHTTPException, raise_unclassified_rule_violation
from easyaudit_next.main import create_app
from easyaudit_next.rules import FieldError, FieldErrorCode, RuleCode, RuleViolation


def _client_with_routes() -> TestClient:
    app = create_app()

    @app.get("/boom/rule")
    def boom_rule() -> None:
        raise RuleViolation(
            RuleCode.FINDING_MISSING_PARTICIPANT_ROLES,
            "Issuing a Process Review Finding requires participant role(s): owner",
            params={"roles": ("responsible_department", "owner")},
        )

    @app.get("/boom/fields")
    def boom_fields() -> None:
        raise RuleViolation(
            RuleCode.REQUEST_INVALID,
            "root_cause must be a non-blank string",
            errors=(
                FieldError(
                    "root_cause",
                    FieldErrorCode.TOO_LONG,
                    {"max": 5},
                    "root_cause is too long",
                ),
            ),
        )

    @app.get("/boom/coded")
    def boom_coded() -> None:
        raise CodedHTTPException(
            400, RuleCode.PASSWORD_CURRENT_INVALID, "Current password is invalid"
        )

    @app.get("/boom/bare")
    def boom_bare() -> None:
        try:
            raise ValueError("something unclassified")
        except ValueError as exc:
            raise_unclassified_rule_violation(exc)

    return TestClient(app)


def test_rule_violation_body_has_detail_code_params_and_empty_errors() -> None:
    response = _client_with_routes().get("/boom/rule")

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Issuing a Process Review Finding requires participant role(s): owner",
        "code": "finding.missing_participant_roles",
        "params": {"roles": ["responsible_department", "owner"]},
        "errors": [],
    }


def test_field_errors_are_listed_without_english_messages() -> None:
    response = _client_with_routes().get("/boom/fields")

    assert response.status_code == 422
    assert response.json()["code"] == "request.invalid"
    assert response.json()["errors"] == [
        {"field": "root_cause", "code": "too_long", "params": {"max": 5}}
    ]


def test_coded_http_exception_keeps_its_status_and_code() -> None:
    response = _client_with_routes().get("/boom/coded")

    assert response.status_code == 400
    assert response.json()["code"] == "password.current_invalid"
    assert response.json()["detail"] == "Current password is invalid"


def test_a_bare_value_error_is_still_422_with_the_unspecified_code() -> None:
    response = _client_with_routes().get("/boom/bare")

    assert response.status_code == 422
    assert response.json()["code"] == "rule.unspecified"


def _post(path: str, payload: dict[str, Any]) -> Any:
    app = create_app()
    app.dependency_overrides[require_business_identity] = lambda: object()
    app.dependency_overrides[get_database_session] = lambda: object()
    return TestClient(app).post(path, json=payload)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"scenario_key": "process_review", "scenario_version": 1, "title": ""},
            {"field": "title", "code": "too_short", "params": {"min": 1}},
        ),
        (
            {"scenario_key": "process_review", "scenario_version": 1, "title": "x" * 301},
            {"field": "title", "code": "too_long", "params": {"max": 300}},
        ),
        (
            {"scenario_key": "process_review", "title": "ok"},
            {"field": "scenario_version", "code": "required", "params": {}},
        ),
        (
            {"scenario_key": "process_review", "scenario_version": 0, "title": "ok"},
            {"field": "scenario_version", "code": "range", "params": {"min": 1}},
        ),
    ],
)
def test_pydantic_validation_errors_use_the_same_envelope(
    payload: dict[str, Any], expected: dict[str, Any]
) -> None:
    response = _post("/api/v1/review-cases", payload)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "request.invalid"
    assert body["detail"] == "Request validation failed"
    assert body["params"] == {}
    assert expected in body["errors"]


def test_validation_errors_never_echo_the_submitted_input() -> None:
    secret = "hunter2-secret-value"
    response = _post("/api/v1/review-cases", {"title": secret * 40, "scenario_version": "x"})

    assert response.status_code == 422
    assert secret not in response.text


def test_openapi_declares_the_rule_error_response_for_business_routes() -> None:
    schema = create_app().openapi()

    response = schema["paths"]["/api/v1/review-cases"]["post"]["responses"]["422"]
    assert response["content"]["application/json"]["schema"]["$ref"].endswith(
        "/RuleErrorResponse"
    )
    schemas = schema["components"]["schemas"]
    assert schemas["RuleErrorResponse"]["properties"]["code"]["$ref"].endswith("/RuleCode")
    assert "finding.missing_participant_roles" in schemas["RuleCode"]["enum"]
