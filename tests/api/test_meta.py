from fastapi.testclient import TestClient

from easyaudit_next.main import create_app

client = TestClient(create_app())


def test_health_endpoint_reports_m14() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "stage": "M1.4"}


def test_domain_metadata_exposes_corrected_boundaries() -> None:
    response = client.get("/api/v1/meta/domain-model")
    payload = response.json()

    assert response.status_code == 200
    assert payload["backend"] == "Python/FastAPI"
    assert payload["stage"] == "M1.4"
    assert "Organization" in payload["concepts"]
    assert "ActionAssignee" in payload["concepts"]
    assert "Scenario" in payload["concepts"]


def test_openapi_contract_has_stable_operation_ids() -> None:
    schema = client.get("/openapi.json").json()

    assert schema["paths"]["/health"]["get"]["operationId"] == "getHealth"
    assert schema["paths"]["/api/v1/meta/domain-model"]["get"]["operationId"] == "getDomainModel"
    assert schema["paths"]["/api/v1/auth/login"]["post"]["operationId"] == "login"
    assert schema["paths"]["/api/v1/admin/users"]["post"]["operationId"] == "createAdminUser"
    assert schema["paths"]["/api/v1/admin/scenarios"]["get"]["operationId"] == "listAdminScenarios"
    assert (
        schema["paths"]["/api/v1/admin/scenarios/{key}/versions"]["get"]["operationId"]
        == "listAdminScenarioVersions"
    )
    assert "/api/v1/review-cases" not in schema["paths"]
    assert "/api/v1/findings" not in schema["paths"]
