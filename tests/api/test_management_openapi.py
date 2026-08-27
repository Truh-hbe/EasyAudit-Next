from fastapi.testclient import TestClient

from easyaudit_next.main import create_app


def test_management_openapi_exposes_read_only_collection_and_progress() -> None:
    schema = create_app().openapi()
    collection = schema["paths"]["/api/v1/management/review-cases"]
    progress = schema["paths"]["/api/v1/management/review-cases/{case_id}/progress"]

    assert set(collection) == {"get"}
    assert set(progress) == {"get"}
    assert collection["get"]["operationId"] == "listManagedReviewCases"
    assert progress["get"]["operationId"] == "getManagedReviewCaseProgress"
    assert collection["get"]["tags"] == ["management"]
    assert progress["get"]["tags"] == ["management"]

    collection_schema = collection["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    progress_schema = progress["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert collection_schema["$ref"].endswith("/ManagementCaseCollectionResponse")
    assert progress_schema["$ref"].endswith("/ManagementCaseProgressResponse")


def test_management_collection_documents_bounded_pagination() -> None:
    schema = create_app().openapi()
    operation = schema["paths"]["/api/v1/management/review-cases"]["get"]
    parameters = {item["name"]: item for item in operation["parameters"]}

    assert parameters["limit"]["schema"]["minimum"] == 1
    assert parameters["limit"]["schema"]["maximum"] == 100
    assert parameters["limit"]["schema"]["default"] == 50
    assert parameters["offset"]["schema"]["minimum"] == 0
    assert parameters["offset"]["schema"]["default"] == 0


def test_management_endpoints_require_existing_business_identity() -> None:
    client = TestClient(create_app())

    collection = client.get("/api/v1/management/review-cases")
    progress = client.get(
        "/api/v1/management/review-cases/00000000-0000-0000-0000-000000000001/progress"
    )

    assert collection.status_code == 401
    assert progress.status_code == 401
    assert collection.json()["detail"] == "Authentication required"
    assert progress.json()["detail"] == "Authentication required"
