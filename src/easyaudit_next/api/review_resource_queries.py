from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from easyaudit_next.api.dependencies import BusinessIdentity, DatabaseSession
from easyaudit_next.api.review_contracts import SubmissionResponse
from easyaudit_next.composition import build_review_resource_context_query_service
from easyaudit_next.review_core.application.review_planning import ReviewAuthorizationError
from easyaudit_next.review_core.domain.ids import ActionItemId, FindingId
from easyaudit_next.review_core.domain.models import AssignmentRole, Submission
from easyaudit_next.review_core.domain.scenario_capabilities import ActorKind
from easyaudit_next.review_resource_queries.context_service import (
    ActionAssigneeView,
    AssignmentCandidateView,
    FindingParticipantView,
    ResourceActivityView,
)
from easyaudit_next.review_resource_queries.schemas import (
    ActionAssigneeViewResponse,
    ActionItemActivityResponse,
    AssignmentCandidateResponse,
    FindingActivityResponse,
    FindingParticipantViewResponse,
)

review_resource_query_router = APIRouter(prefix="/api/v1", tags=["review-resource-queries"])


def _raise_api_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ReviewAuthorizationError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unexpected resource query failure",
    ) from exc


def _participant_view_response(item: FindingParticipantView) -> FindingParticipantViewResponse:
    return FindingParticipantViewResponse(
        finding_id=item.finding_id,
        actor_kind=item.actor_kind,
        actor_id=item.actor_id,
        role_key=item.role_key,
        assigned_at=item.assigned_at,
        display_name=item.display_name,
    )


def _assignee_view_response(item: ActionAssigneeView) -> ActionAssigneeViewResponse:
    return ActionAssigneeViewResponse(
        action_item_id=item.action_item_id,
        actor_kind=item.actor_kind,
        actor_id=item.actor_id,
        role=item.role,
        assigned_at=item.assigned_at,
        display_name=item.display_name,
    )


def _candidate_response(item: AssignmentCandidateView) -> AssignmentCandidateResponse:
    return AssignmentCandidateResponse(
        actor_kind=item.actor_kind,
        actor_id=item.actor_id,
        display_name=item.display_name,
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


def _finding_activity_response(item: ResourceActivityView) -> FindingActivityResponse:
    return FindingActivityResponse(
        id=item.id,
        subject_id=item.subject_id,
        event_type=item.event_type,
        actor_id=item.actor_id,
        occurred_at=item.occurred_at,
    )


def _action_activity_response(item: ResourceActivityView) -> ActionItemActivityResponse:
    return ActionItemActivityResponse(
        id=item.id,
        subject_id=item.subject_id,
        event_type=item.event_type,
        actor_id=item.actor_id,
        occurred_at=item.occurred_at,
    )


@review_resource_query_router.get(
    "/findings/{finding_id}/participant-views",
    response_model=list[FindingParticipantViewResponse],
    operation_id="listFindingParticipantViews",
)
def list_finding_participant_views(
    finding_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[FindingParticipantViewResponse]:
    service = build_review_resource_context_query_service(session)
    try:
        items = service.list_finding_participant_views(identity.user, FindingId(finding_id))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return [_participant_view_response(item) for item in items]


@review_resource_query_router.get(
    "/action-items/{action_item_id}/assignee-views",
    response_model=list[ActionAssigneeViewResponse],
    operation_id="listActionAssigneeViews",
)
def list_action_assignee_views(
    action_item_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[ActionAssigneeViewResponse]:
    service = build_review_resource_context_query_service(session)
    try:
        items = service.list_action_assignee_views(identity.user, ActionItemId(action_item_id))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return [_assignee_view_response(item) for item in items]


@review_resource_query_router.get(
    "/findings/{finding_id}/participant-candidates",
    response_model=list[AssignmentCandidateResponse],
    operation_id="searchFindingParticipantCandidates",
)
def search_finding_participant_candidates(
    finding_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
    role_key: Annotated[str, Query(min_length=1, max_length=100)],
    actor_kind: ActorKind,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
) -> list[AssignmentCandidateResponse]:
    service = build_review_resource_context_query_service(session)
    try:
        items = service.search_finding_participant_candidates(
            identity.user,
            FindingId(finding_id),
            role_key=role_key,
            actor_kind=actor_kind,
            search_text=q,
            limit=limit,
        )
    except (ReviewAuthorizationError, LookupError, ValueError) as exc:
        _raise_api_error(exc)
    return [_candidate_response(item) for item in items]


@review_resource_query_router.get(
    "/action-items/{action_item_id}/assignee-candidates",
    response_model=list[AssignmentCandidateResponse],
    operation_id="searchActionAssigneeCandidates",
)
def search_action_assignee_candidates(
    action_item_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
    role: AssignmentRole,
    actor_kind: ActorKind,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
) -> list[AssignmentCandidateResponse]:
    service = build_review_resource_context_query_service(session)
    try:
        items = service.search_action_assignee_candidates(
            identity.user,
            ActionItemId(action_item_id),
            role=role,
            actor_kind=actor_kind,
            search_text=q,
            limit=limit,
        )
    except (ReviewAuthorizationError, LookupError, ValueError) as exc:
        _raise_api_error(exc)
    return [_candidate_response(item) for item in items]


@review_resource_query_router.get(
    "/action-items/{action_item_id}/transfer-candidates",
    response_model=list[AssignmentCandidateResponse],
    operation_id="searchActionTransferCandidates",
)
def search_action_transfer_candidates(
    action_item_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
) -> list[AssignmentCandidateResponse]:
    service = build_review_resource_context_query_service(session)
    try:
        items = service.search_action_transfer_candidates(
            identity.user,
            ActionItemId(action_item_id),
            search_text=q,
            limit=limit,
        )
    except (ReviewAuthorizationError, LookupError, ValueError) as exc:
        _raise_api_error(exc)
    return [_candidate_response(item) for item in items]


@review_resource_query_router.get(
    "/findings/{finding_id}/submissions",
    response_model=list[SubmissionResponse],
    operation_id="listFindingSubmissions",
)
def list_finding_submissions(
    finding_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[SubmissionResponse]:
    service = build_review_resource_context_query_service(session)
    try:
        submissions = service.list_finding_submissions(identity.user, FindingId(finding_id))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return [_submission_response(item) for item in submissions]


@review_resource_query_router.get(
    "/findings/{finding_id}/activities",
    response_model=list[FindingActivityResponse],
    operation_id="listFindingActivities",
)
def list_finding_activities(
    finding_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[FindingActivityResponse]:
    service = build_review_resource_context_query_service(session)
    try:
        activities = service.list_finding_activities(identity.user, FindingId(finding_id))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return [_finding_activity_response(item) for item in activities]


@review_resource_query_router.get(
    "/action-items/{action_item_id}/activities",
    response_model=list[ActionItemActivityResponse],
    operation_id="listActionItemActivities",
)
def list_action_item_activities(
    action_item_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[ActionItemActivityResponse]:
    service = build_review_resource_context_query_service(session)
    try:
        activities = service.list_action_activities(identity.user, ActionItemId(action_item_id))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return [_action_activity_response(item) for item in activities]
