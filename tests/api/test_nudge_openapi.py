from easyaudit_next.main import create_app


def test_manual_nudge_routes_are_post_only_and_server_resolve_recipients() -> None:
    schema = create_app().openapi()

    finding = schema["paths"]["/api/v1/findings/{finding_id}/nudge"]
    action = schema["paths"]["/api/v1/action-items/{action_item_id}/nudge"]

    assert set(finding) == {"post"}
    assert set(action) == {"post"}
    assert finding["post"]["operationId"] == "nudgeFinding"
    assert action["post"]["operationId"] == "nudgeActionItem"

    for operation in (finding["post"], action["post"]):
        assert "requestBody" not in operation
        parameter_names = {item["name"] for item in operation.get("parameters", [])}
        assert "recipient_user_id" not in parameter_names
        assert "recipient_user_ids" not in parameter_names
