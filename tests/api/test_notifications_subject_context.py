from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import easyaudit_next.notifications.api as notification_api
from easyaudit_next.api.dependencies import get_database_session, require_business_identity
from easyaudit_next.main import create_app
from easyaudit_next.notifications.models import (
    ActionItemNotificationSubject,
    ActivityNotificationOrigin,
    NotificationId,
    NotificationInboxPage,
    NotificationItem,
    NotificationKind,
)
from easyaudit_next.notifications.subject_context import NotificationSubjectContext
from easyaudit_next.review_core.domain.ids import ActionItemId, ActivityId
from tests.api.test_notifications_privacy import _identity

NOW = datetime(2026, 10, 7, tzinfo=UTC)


def _item() -> NotificationItem:
    identity = _identity()
    return NotificationItem(
        id=NotificationId(uuid4()),
        organization_id=identity.user.organization_id,
        recipient_user_id=identity.user.id,
        kind=NotificationKind.ACTION_ASSIGNEE_ADDED,
        origin=ActivityNotificationOrigin(ActivityId(uuid4())),
        subject=ActionItemNotificationSubject(ActionItemId(uuid4())),
        title="指派整改项",
        body="您已被指派处理一个整改项。",
        created_at=NOW,
        read_at=None,
    )


class _Service:
    def __init__(self, item: NotificationItem) -> None:
        self._item = item

    def get_inbox(self, *_args: object, **_kwargs: object) -> NotificationInboxPage:
        return NotificationInboxPage(items=(self._item,), unread_count=1, limit=50, offset=0)

    def mark_read(self, *_args: object) -> NotificationItem:
        return self._item


class _Resolver:
    def __init__(self, contexts: dict[NotificationId, NotificationSubjectContext]) -> None:
        self.contexts = contexts

    def resolve(self, *_args: object) -> dict[NotificationId, NotificationSubjectContext]:
        return self.contexts


def _client(
    monkeypatch: pytest.MonkeyPatch,
    item: NotificationItem,
    contexts: dict[NotificationId, NotificationSubjectContext],
) -> TestClient:
    app = create_app()
    app.dependency_overrides[require_business_identity] = _identity
    app.dependency_overrides[get_database_session] = object
    monkeypatch.setattr(notification_api, "build_notification_service", lambda _s: _Service(item))
    monkeypatch.setattr(
        notification_api,
        "build_notification_subject_context_resolver",
        lambda _s: _Resolver(contexts),
    )
    return TestClient(app)


def test_visible_subject_context_is_attached_to_inbox_and_mark_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _item()
    context = NotificationSubjectContext("整改A", "发现B", None, ("primary",))
    client = _client(monkeypatch, item, {item.id: context})

    listed = client.get("/api/v1/me/notifications").json()["items"][0]
    read = client.post(f"/api/v1/me/notifications/{item.id}/read").json()

    expected = {
        "title": "整改A",
        "finding_title": "发现B",
        "case_title": None,
        "role_keys": ["primary"],
    }
    assert listed["subject"]["context"] == expected
    assert read["subject"]["context"] == expected
    assert listed["title"] == "指派整改项"  # delivered copy is never rewritten


def test_invisible_subject_has_no_context(monkeypatch: pytest.MonkeyPatch) -> None:
    item = _item()
    client = _client(monkeypatch, item, {})

    subject = client.get("/api/v1/me/notifications").json()["items"][0]["subject"]

    assert subject["context"] is None
    assert set(subject) == {"kind", "id", "context"}
