from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from easyaudit_next.api.dependencies import BusinessIdentity, DatabaseSession
from easyaudit_next.composition import (
    build_notification_service,
    build_notification_subject_context_resolver,
)
from easyaudit_next.notifications.models import (
    ActionItemNotificationSubject,
    FindingNotificationSubject,
    NotificationId,
    NotificationItem,
    NotificationSubjectKind,
    ReviewCaseNotificationSubject,
)
from easyaudit_next.notifications.schemas import (
    NotificationInboxResponse,
    NotificationResponse,
    NotificationSubjectContextResponse,
    NotificationSubjectResponse,
)
from easyaudit_next.notifications.subject_context import NotificationSubjectContext

notification_router = APIRouter(prefix="/api/v1", tags=["notifications"])


def _notification_response(
    item: NotificationItem,
    contexts: dict[NotificationId, NotificationSubjectContext],
) -> NotificationResponse:
    if isinstance(item.subject, ReviewCaseNotificationSubject):
        subject = NotificationSubjectResponse(
            kind=NotificationSubjectKind.REVIEW_CASE,
            id=item.subject.review_case_id,
        )
    elif isinstance(item.subject, FindingNotificationSubject):
        subject = NotificationSubjectResponse(
            kind=NotificationSubjectKind.FINDING,
            id=item.subject.finding_id,
        )
    elif isinstance(item.subject, ActionItemNotificationSubject):
        subject = NotificationSubjectResponse(
            kind=NotificationSubjectKind.ACTION_ITEM,
            id=item.subject.action_item_id,
        )
    else:
        raise RuntimeError("Unsupported Notification subject")
    context = contexts.get(item.id)
    if context is not None:
        subject = subject.model_copy(
            update={
                "context": NotificationSubjectContextResponse(
                    title=context.title,
                    finding_title=context.finding_title,
                    case_title=context.case_title,
                    role_keys=context.role_keys,
                )
            }
        )
    return NotificationResponse(
        id=item.id,
        kind=item.kind,
        origin_kind=item.origin_kind,
        origin_activity_id=item.origin_activity_id,
        automatic_origin_key=item.automatic_origin_key,
        subject=subject,
        title=item.title,
        body=item.body,
        created_at=item.created_at,
        read_at=item.read_at,
    )


@notification_router.get(
    "/me/notifications",
    response_model=NotificationInboxResponse,
    operation_id="listMyNotifications",
)
def list_my_notifications(
    identity: BusinessIdentity,
    session: DatabaseSession,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NotificationInboxResponse:
    service = build_notification_service(session)
    page = service.get_inbox(
        identity.user.organization_id,
        identity.user.id,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
    )
    contexts = build_notification_subject_context_resolver(session).resolve(
        identity.user,
        page.items,
    )
    return NotificationInboxResponse(
        items=tuple(_notification_response(item, contexts) for item in page.items),
        unread_count=page.unread_count,
        limit=page.limit,
        offset=page.offset,
    )


@notification_router.post(
    "/me/notifications/{notification_id}/read",
    response_model=NotificationResponse,
    operation_id="markMyNotificationRead",
)
def mark_my_notification_read(
    notification_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> NotificationResponse:
    service = build_notification_service(session)
    try:
        item = service.mark_read(
            identity.user.organization_id,
            identity.user.id,
            notification_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        ) from exc
    contexts = build_notification_subject_context_resolver(session).resolve(
        identity.user,
        (item,),
    )
    return _notification_response(item, contexts)
