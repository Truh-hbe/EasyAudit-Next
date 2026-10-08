import pytest
from fastapi.testclient import TestClient

from easyaudit_next.api.dependencies import get_database_session, require_business_identity
from easyaudit_next.main import create_app


@pytest.mark.parametrize(
    ("path", "payload", "field_name"),
    [
        (
            "/api/v1/review-plans",
            {
                "title": "Naive plan",
                "planned_start_at": "2026-08-25T09:00:00",
            },
            "planned_start_at",
        ),
        (
            "/api/v1/review-cases",
            {
                "scenario_key": "process_review",
                "scenario_version": 1,
                "title": "Naive case",
                "planned_end_at": "2026-08-25T17:00:00",
                "scenario_data": {},
            },
            "planned_end_at",
        ),
    ],
)
def test_planning_create_rejects_datetime_without_offset(
    path: str,
    payload: dict[str, object],
    field_name: str,
) -> None:
    app = create_app()
    app.dependency_overrides[require_business_identity] = lambda: object()
    app.dependency_overrides[get_database_session] = lambda: object()

    response = TestClient(app).post(path, json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "request.invalid"
    assert {"field": field_name, "code": "invalid_datetime", "params": {}} in body["errors"]
