from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from easyaudit_next.notifications.models import (
    NotificationKind,
    NotificationOriginKind,
    NotificationSubjectKind,
)


class NotificationSubjectContextResponse(BaseModel):
    """What the target is, as the recipient may see it now; absent when not visible."""

    model_config = ConfigDict(frozen=True)

    title: str
    finding_title: str | None = None
    case_title: str | None = None
    role_keys: tuple[str, ...] = ()


class NotificationSubjectResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: NotificationSubjectKind
    id: UUID
    context: NotificationSubjectContextResponse | None = None


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
