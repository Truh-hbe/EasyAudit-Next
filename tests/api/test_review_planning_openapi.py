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
    assert "get" in paths["/api/v1/review-cases/{case_id}/activities"]
    assert "post" in paths["/api/v1/review-cases/{case_id}/transitions"]
    assert "post" in paths["/api/v1/review-cases/{case_id}/findings"]
    assert "get" in paths["/api/v1/review-cases/{case_id}/findings"]
    assert "get" in paths["/api/v1/findings/{finding_id}"]
    assert "patch" not in paths["/api/v1/findings/{finding_id}"]
    assert "delete" not in paths["/api/v1/findings/{finding_id}"]
    assert "post" in paths["/api/v1/findings/{finding_id}/participants"]
    assert "get" in paths["/api/v1/findings/{finding_id}/participants"]
    assert "post" in paths["/api/v1/findings/{finding_id}/transitions"]

    create_schema = schema["components"]["schemas"]["ReviewCaseCreateRequest"]
    assert "lifecycle" not in create_schema.get("properties", {})
    finding_create_schema = schema["components"]["schemas"]["FindingCreateRequest"]
    assert "lifecycle" not in finding_create_schema.get("properties", {})


def test_review_case_collection_contract_is_bounded_and_enveloped() -> None:
    schema = create_app().openapi()
    operation = schema["paths"]["/api/v1/review-cases"]["get"]
    parameters = {item["name"]: item for item in operation["parameters"]}

    assert parameters["limit"]["schema"] == {
        "type": "integer",
        "maximum": 100,
        "minimum": 1,
        "default": 50,
        "title": "Limit",
    }
    assert parameters["offset"]["schema"] == {
        "type": "integer",
        "minimum": 0,
        "default": 0,
        "title": "Offset",
    }

    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"].endswith("/ReviewCaseCollectionResponse")
    collection_schema = schema["components"]["schemas"]["ReviewCaseCollectionResponse"]
    assert set(collection_schema["required"]) == {"items", "total", "limit", "offset"}


def test_case_member_view_and_activity_contracts_are_presentation_safe() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]

    member_get = paths["/api/v1/review-cases/{case_id}/members"]["get"]
    member_items = member_get["responses"]["200"]["content"]["application/json"]["schema"][
        "items"
    ]
    assert member_items["$ref"].endswith("/CaseMemberViewResponse")
    member_schema = schema["components"]["schemas"]["CaseMemberViewResponse"]
    assert set(member_schema["required"]) == {
        "case_id",
        "user_id",
        "role_key",
        "joined_at",
        "display_name",
    }

    member_post = paths["/api/v1/review-cases/{case_id}/members"]["post"]
    command_response = member_post["responses"]["201"]["content"]["application/json"]["schema"]
    assert command_response["$ref"].endswith("/CaseMemberResponse")

    activity_get = paths["/api/v1/review-cases/{case_id}/activities"]["get"]
    activity_items = activity_get["responses"]["200"]["content"]["application/json"]["schema"][
        "items"
    ]
    assert activity_items["$ref"].endswith("/ReviewCaseActivityResponse")
    activity_schema = schema["components"]["schemas"]["ReviewCaseActivityResponse"]
    assert set(activity_schema["properties"]) == {
        "id",
        "subject_type",
        "subject_id",
        "event_type",
        "actor_id",
        "occurred_at",
    }
    assert "metadata" not in activity_schema["properties"]
