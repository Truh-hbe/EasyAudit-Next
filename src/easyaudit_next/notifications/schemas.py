from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from easyaudit_next.notifications.models import (
    NotificationKind,
    NotificationOriginKind,
    NotificationSubjectKind,
)


class NotificationSubjectResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: NotificationSubjectKind
    id: UUID


class NotificationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    kind: NotificationKind
    origin_kind: NotificationOriginKind
    origin_activity_id: UUID | None
    automatic_origin_key: str | None
    subject: NotificationSubjectResponse
    title: str
    body: str
    created_at: datetime
    read_at: datetime | None


class NotificationInboxResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[NotificationResponse, ...]
    unread_count: int
    limit: int
    offset: int
