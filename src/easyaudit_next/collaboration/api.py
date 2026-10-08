from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from easyaudit_next.api.dependencies import BusinessIdentity, DatabaseSession
from easyaudit_next.collaboration.schemas import NudgeResponse
from easyaudit_next.composition import build_manual_nudge_service

collaboration_router = APIRouter(prefix="/api/v1", tags=["collaboration"])


@collaboration_router.post(
    "/findings/{finding_id}/nudge",
    response_model=NudgeResponse,
    operation_id="nudgeFinding",
)
def nudge_finding(
    finding_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> NudgeResponse:
    try:
        result = build_manual_nudge_service(session).nudge_finding(
            identity.user,
            finding_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Finding not found",
        ) from exc
    return NudgeResponse(
        activity_id=result.activity_id,
        recipient_count=result.recipient_count,
    )


@collaboration_router.post(
    "/action-items/{action_item_id}/nudge",
    response_model=NudgeResponse,
    operation_id="nudgeActionItem",
)
def nudge_action_item(
    action_item_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> NudgeResponse:
    try:
        result = build_manual_nudge_service(session).nudge_action_item(
            identity.user,
            action_item_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ActionItem not found",
        ) from exc
    return NudgeResponse(
        activity_id=result.activity_id,
        recipient_count=result.recipient_count,
    )
