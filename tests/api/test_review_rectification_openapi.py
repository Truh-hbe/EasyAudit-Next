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
    transfer = paths["/api/v1/action-items/{action_item_id}/transfer-and-reopen"]["post"]
    assert transfer["operationId"] == "transferAndReopenActionItem"
    transfer_schema = schema["components"]["schemas"]["ActionItemTransferRequest"]
    assert set(transfer_schema["required"]) == {"new_executor_id", "reason"}
    assert "get" in paths["/api/v1/action-items/{action_item_id}/transfer-candidates"]
    assert "post" not in paths["/api/v1/action-items/{action_item_id}/evidences"]
    assert "post" in paths["/api/v1/action-items/{action_item_id}/evidence-uploads"]
    assert "get" in paths["/api/v1/action-items/{action_item_id}/evidences"]
    assert "post" in paths["/api/v1/findings/{finding_id}/rectification-submissions"]
    assert "get" in paths["/api/v1/findings/{finding_id}/rectification-submissions"]

    create_schema = schema["components"]["schemas"]["ActionItemCreateRequest"]
    assert "lifecycle" not in create_schema.get("properties", {})
    # Evidence has no JSON request schema: key, size and sha256 are computed by the server.
    assert "EvidenceRegisterRequest" not in schema["components"]["schemas"]
    upload = paths["/api/v1/action-items/{action_item_id}/evidence-uploads"]["post"]
    assert "application/octet-stream" in upload["requestBody"]["content"]
    assert {"X-Evidence-Filename", "description"} <= {p["name"] for p in upload["parameters"]}
    assert not {"storage_key", "sha256", "size_bytes"} & {p["name"] for p in upload["parameters"]}
    submission_schema = schema["components"]["schemas"]["RectificationSubmissionRequest"]
    assert "purpose" not in submission_schema.get("properties", {})
