from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from easyaudit_next.api.dependencies import BusinessIdentity, DatabaseSession
from easyaudit_next.api.review_contracts import (
    ActionAssigneeCreateRequest,
    ActionAssigneeResponse,
    ActionItemCreateRequest,
    ActionItemResponse,
    ActionItemTransitionRequest,
    EvidenceResponse,
    FindingResponse,
    RectificationSubmissionRequest,
    RectificationSubmissionResponse,
    SubmissionResponse,
)
from easyaudit_next.composition import (
    build_notification_orchestrator,
    build_rectification_service,
)
from easyaudit_next.platform.domain.ids import DepartmentId, UserId
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
)
from easyaudit_next.review_core.application.review_planning import ReviewAuthorizationError
from easyaudit_next.review_core.application.review_rectification import (
    ConcurrentActionItemTransitionError,
)
from easyaudit_next.review_core.domain.ids import ActionItemId, FindingId
from easyaudit_next.review_core.domain.models import (
    ActionAssignee,
    ActionItem,
    DepartmentActor,
    Evidence,
    Finding,
    Submission,
    UserActor,
)
from easyaudit_next.review_core.domain.scenario_capabilities import ActorKind

review_rectification_router = APIRouter(prefix="/api/v1", tags=["review-rectification"])


def _finding_response(finding: Finding) -> FindingResponse:
    return FindingResponse(
        id=finding.id,
        organization_id=finding.organization_id,
        case_id=finding.case_id,
        title=finding.title,
        description=finding.description,
        severity=finding.severity,
        lifecycle=finding.lifecycle,
        scenario_data=dict(finding.scenario_data),
        raised_by=finding.raised_by,
        raised_at=finding.raised_at,
    )


def _action_response(action_item: ActionItem) -> ActionItemResponse:
    return ActionItemResponse(
        id=action_item.id,
        organization_id=action_item.organization_id,
        finding_id=action_item.finding_id,
        title=action_item.title,
        lifecycle=action_item.lifecycle,
        due_at=action_item.due_at,
        completed_at=action_item.completed_at,
    )


def _assignee_response(assignee: ActionAssignee) -> ActionAssigneeResponse:
    if isinstance(assignee.actor, UserActor):
        actor_kind = ActorKind.USER
        actor_id: UUID = assignee.actor.user_id
    else:
        actor_kind = ActorKind.DEPARTMENT
        actor_id = assignee.actor.department_id
    return ActionAssigneeResponse(
        action_item_id=assignee.action_item_id,
        actor_kind=actor_kind,
        actor_id=actor_id,
        role=assignee.role,
        assigned_at=assignee.assigned_at,
    )


def _evidence_response(evidence: Evidence) -> EvidenceResponse:
    return EvidenceResponse(
        id=evidence.id,
        organization_id=evidence.organization_id,
        action_item_id=evidence.action_item_id,
        storage_key=evidence.storage_key,
        original_name=evidence.original_name,
        content_type=evidence.content_type,
        size_bytes=evidence.size_bytes,
        sha256=evidence.sha256,
        description=evidence.description,
        uploaded_by=evidence.uploaded_by,
        created_at=evidence.created_at,
    )


def _submission_response(submission: Submission) -> SubmissionResponse:
    return SubmissionResponse(
        id=submission.id,
        organization_id=submission.organization_id,
        case_id=submission.case_id,
        finding_id=submission.finding_id,
        purpose=submission.purpose,
        submitted_by=submission.submitted_by,
        submitted_at=submission.submitted_at,
        payload=dict(submission.payload),
    )


def _raise_api_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ReviewAuthorizationError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(
        exc,
        (ConcurrentActionItemTransitionError, ConcurrentFindingTransitionError, IntegrityError),
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unexpected rectification operation failure",
    ) from exc


@review_rectification_router.post(
    "/findings/{finding_id}/actions",
    response_model=ActionItemResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createActionItem",
)
def create_action_item(
    finding_id: UUID,
    payload: ActionItemCreateRequest,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> ActionItemResponse:
    service = build_rectification_service(session)
    try:
        action_item = service.create_action_item(
            identity.user,
            FindingId(finding_id),
            payload.title,
            due_at=payload.due_at,
        )
    except (
        ConcurrentFindingTransitionError,
        ReviewAuthorizationError,
        LookupError,
        ValueError,
        IntegrityError,
    ) as exc:
        _raise_api_error(exc)
    return _action_response(action_item)


@review_rectification_router.get(
    "/findings/{finding_id}/actions",
    response_model=list[ActionItemResponse],
    operation_id="listActionItems",
)
def list_action_items(
    finding_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[ActionItemResponse]:
    service = build_rectification_service(session)
    try:
        actions = service.list_action_items(identity.user, FindingId(finding_id))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return [_action_response(action_item) for action_item in actions]


@review_rectification_router.get(
    "/action-items/{action_item_id}",
    response_model=ActionItemResponse,
    operation_id="getActionItem",
)
def get_action_item(
    action_item_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> ActionItemResponse:
    service = build_rectification_service(session)
    try:
        action_item = service.get_action_item(identity.user, ActionItemId(action_item_id))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return _action_response(action_item)


@review_rectification_router.post(
    "/action-items/{action_item_id}/assignees",
    response_model=ActionAssigneeResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="addActionAssignee",
)
def add_action_assignee(
    action_item_id: UUID,
    payload: ActionAssigneeCreateRequest,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> ActionAssigneeResponse:
    assignee_actor = (
        UserActor(UserId(payload.actor_id))
        if payload.actor_kind is ActorKind.USER
        else DepartmentActor(DepartmentId(payload.actor_id))
    )
    service = build_rectification_service(session)
    notifications = build_notification_orchestrator(session)
    try:
        result = service.add_assignee_result(
            identity.user,
            ActionItemId(action_item_id),
            assignee_actor,
            payload.role,
        )
        notifications.action_assignee_added(result)
    except (
        ConcurrentFindingTransitionError,
        ReviewAuthorizationError,
        LookupError,
        ValueError,
        IntegrityError,
    ) as exc:
        _raise_api_error(exc)
    return _assignee_response(result.assignee)


@review_rectification_router.get(
    "/action-items/{action_item_id}/assignees",
    response_model=list[ActionAssigneeResponse],
    operation_id="listActionAssignees",
)
def list_action_assignees(
    action_item_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[ActionAssigneeResponse]:
    service = build_rectification_service(session)
    try:
        assignees = service.list_assignees(identity.user, ActionItemId(action_item_id))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return [_assignee_response(assignee) for assignee in assignees]


@review_rectification_router.post(
    "/action-items/{action_item_id}/transitions",
    response_model=ActionItemResponse,
    operation_id="transitionActionItem",
)
def transition_action_item(
    action_item_id: UUID,
    payload: ActionItemTransitionRequest,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> ActionItemResponse:
    service = build_rectification_service(session)
    try:
        action_item = service.transition_action_item(
            identity.user,
            ActionItemId(action_item_id),
            payload.action,
            reason=payload.reason,
        )
    except (
        ConcurrentActionItemTransitionError,
        ConcurrentFindingTransitionError,
        ReviewAuthorizationError,
        LookupError,
        ValueError,
        IntegrityError,
    ) as exc:
        _raise_api_error(exc)
    return _action_response(action_item)


@review_rectification_router.get(
    "/action-items/{action_item_id}/evidences",
    response_model=list[EvidenceResponse],
    operation_id="listActionEvidences",
)
def list_action_evidences(
    action_item_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[EvidenceResponse]:
    service = build_rectification_service(session)
    try:
        evidences = service.list_evidences(identity.user, ActionItemId(action_item_id))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return [_evidence_response(evidence) for evidence in evidences]


@review_rectification_router.post(
    "/findings/{finding_id}/rectification-submissions",
    response_model=RectificationSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="submitRectification",
)
def submit_rectification(
    finding_id: UUID,
    payload: RectificationSubmissionRequest,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> RectificationSubmissionResponse:
    service = build_rectification_service(session)
    notifications = build_notification_orchestrator(session)
    try:
        result = service.submit_rectification_result(
            identity.user,
            FindingId(finding_id),
            payload.action,
            payload.payload,
        )
        notifications.rectification_submitted(result)
    except (
        ConcurrentFindingTransitionError,
        ReviewAuthorizationError,
        LookupError,
        ValueError,
        IntegrityError,
    ) as exc:
        _raise_api_error(exc)
    return RectificationSubmissionResponse(
        submission=_submission_response(result.submission),
        finding=_finding_response(result.finding),
    )


@review_rectification_router.get(
    "/findings/{finding_id}/rectification-submissions",
    response_model=list[SubmissionResponse],
    operation_id="listRectificationSubmissions",
)
def list_rectification_submissions(
    finding_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[SubmissionResponse]:
    service = build_rectification_service(session)
    try:
        submissions = service.list_rectification_submissions(
            identity.user,
            FindingId(finding_id),
        )
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return [_submission_response(submission) for submission in submissions]
