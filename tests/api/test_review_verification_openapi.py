from easyaudit_next.main import create_app


def test_verification_routes_are_explicit_and_do_not_expose_state_patch() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]

    verification_path = "/api/v1/findings/{finding_id}/verification-submissions"
    reopen_path = "/api/v1/findings/{finding_id}/reopen"

    assert "post" in paths[verification_path]
    assert "post" in paths[reopen_path]
    assert "patch" not in paths[verification_path]
    assert "delete" not in paths[verification_path]
    assert "patch" not in paths[reopen_path]
    assert "delete" not in paths[reopen_path]

    verification_schema = schema["components"]["schemas"]["VerificationSubmissionRequest"]
    verification_properties = verification_schema.get("properties", {})
    assert "purpose" not in verification_properties
    assert "lifecycle" not in verification_properties

    reopen_schema = schema["components"]["schemas"]["FindingReopenRequest"]
    assert "lifecycle" not in reopen_schema.get("properties", {})
