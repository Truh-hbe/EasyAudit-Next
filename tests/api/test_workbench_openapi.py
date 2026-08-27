from fastapi.testclient import TestClient

from easyaudit_next.main import create_app


def test_workbench_openapi_exposes_aggregate_read_model() -> None:
    schema = create_app().openapi()
    path = schema["paths"]["/api/v1/me/workbench"]["get"]

    assert path["operationId"] == "getMyWorkbench"
    assert path["tags"] == ["workbench"]
    response_schema = path["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"].endswith("/WorkbenchResponse")

    workbench = schema["components"]["schemas"]["WorkbenchResponse"]
    assert set(workbench["properties"]) == {
        "as_of",
        "case_responsibilities",
        "finding_responsibilities",
        "action_responsibilities",
        "verification_queue",
        "due_soon",
        "overdue",
    }


def test_workbench_requires_existing_authenticated_business_identity() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/me/workbench")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"
