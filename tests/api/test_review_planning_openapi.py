from easyaudit_next.main import create_app


def test_review_planning_routes_are_exposed_without_lifecycle_patch() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]

    assert "post" in paths["/api/v1/review-plans"]
    assert "get" in paths["/api/v1/review-plans"]
    assert "get" in paths["/api/v1/review-plans/{plan_id}"]
    assert "post" in paths["/api/v1/review-cases"]
    assert "get" in paths["/api/v1/review-cases"]
    assert "get" in paths["/api/v1/review-cases/{case_id}"]
    assert "patch" not in paths["/api/v1/review-cases/{case_id}"]
    assert "post" in paths["/api/v1/review-cases/{case_id}/members"]
    assert "get" in paths["/api/v1/review-cases/{case_id}/members"]
    assert "post" in paths["/api/v1/review-cases/{case_id}/transitions"]

    create_schema = schema["components"]["schemas"]["ReviewCaseCreateRequest"]
    assert "lifecycle" not in create_schema.get("properties", {})
