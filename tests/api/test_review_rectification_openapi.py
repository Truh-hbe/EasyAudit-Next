from easyaudit_next.main import create_app


def test_rectification_routes_are_explicit_and_do_not_expose_lifecycle_patch() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]

    assert "post" in paths["/api/v1/findings/{finding_id}/actions"]
    assert "get" in paths["/api/v1/findings/{finding_id}/actions"]
    assert "get" in paths["/api/v1/action-items/{action_item_id}"]
    assert "patch" not in paths["/api/v1/action-items/{action_item_id}"]
    assert "delete" not in paths["/api/v1/action-items/{action_item_id}"]
    assert "post" in paths["/api/v1/action-items/{action_item_id}/assignees"]
    assert "get" in paths["/api/v1/action-items/{action_item_id}/assignees"]
    assert "post" in paths["/api/v1/action-items/{action_item_id}/transitions"]
    assert "post" in paths["/api/v1/action-items/{action_item_id}/evidences"]
    assert "get" in paths["/api/v1/action-items/{action_item_id}/evidences"]
    assert "post" in paths["/api/v1/findings/{finding_id}/rectification-submissions"]
    assert "get" in paths["/api/v1/findings/{finding_id}/rectification-submissions"]

    create_schema = schema["components"]["schemas"]["ActionItemCreateRequest"]
    assert "lifecycle" not in create_schema.get("properties", {})
    evidence_schema = schema["components"]["schemas"]["EvidenceRegisterRequest"]
    assert "uploaded_by" not in evidence_schema.get("properties", {})
    submission_schema = schema["components"]["schemas"]["RectificationSubmissionRequest"]
    assert "purpose" not in submission_schema.get("properties", {})
