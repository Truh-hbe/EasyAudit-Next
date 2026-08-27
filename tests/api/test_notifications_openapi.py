from fastapi.testclient import TestClient

from easyaudit_next.main import create_app


def test_notification_openapi_exposes_bounded_inbox_and_mark_read_only() -> None:
    schema = create_app().openapi()
    inbox_path = schema["paths"]["/api/v1/me/notifications"]
    read_path = schema["paths"]["/api/v1/me/notifications/{notification_id}/read"]

    assert set(inbox_path) == {"get"}
    assert set(read_path) == {"post"}
    assert inbox_path["get"]["operationId"] == "listMyNotifications"
    assert read_path["post"]["operationId"] == "markMyNotificationRead"
    assert inbox_path["get"]["tags"] == ["notifications"]
    assert read_path["post"]["tags"] == ["notifications"]

    response_schema = inbox_path["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema["$ref"].endswith("/NotificationInboxResponse")
    assert "/api/v1/me/notifications/{notification_id}" not in schema["paths"]


def test_notification_endpoints_require_business_authentication() -> None:
    client = TestClient(create_app())

    inbox = client.get("/api/v1/me/notifications")
    mark_read = client.post(
        "/api/v1/me/notifications/00000000-0000-0000-0000-000000000001/read"
    )

    assert inbox.status_code == 401
    assert mark_read.status_code == 401
    assert inbox.json()["detail"] == "Authentication required"
    assert mark_read.json()["detail"] == "Authentication required"
