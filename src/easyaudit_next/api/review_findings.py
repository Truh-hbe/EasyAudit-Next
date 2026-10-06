from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from easyaudit_next.api.dependencies import BusinessIdentity, DatabaseSession
from easyaudit_next.api.errors import raise_database_conflict
from easyaudit_next.api.review_contracts import (
    FindingCreateRequest,
    FindingParticipantCreateRequest,
    FindingParticipantResponse,
    FindingResponse,
    FindingTransitionRequest,
)
from easyaudit_next.composition import (
    build_finding_lifecycle_service,
    build_notification_orchestrator,
)
from easyaudit_next.platform.domain.ids import DepartmentId, UserId
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
)
from easyaudit_next.review_core.application.review_planning import (
    ConcurrentCaseTransitionError,
    ReviewAuthorizationError,
)
from easyaudit_next.review_core.domain.ids import FindingId, ReviewCaseId
from easyaudit_next.review_core.domain.models import (
    DepartmentActor,
    Finding,
    FindingParticipant,
    UserActor,
)
from easyaudit_next.review_core.domain.scenario_capabilities import ActorKind

review_findings_router = APIRouter(prefix="/api/v1", tags=["review-findings"])


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


def _participant_response(participant: FindingParticipant) -> FindingParticipantResponse:
    if isinstance(participant.actor, UserActor):
        actor_kind = ActorKind.USER
        actor_id: UUID = participant.actor.user_id
    else:
        actor_kind = ActorKind.DEPARTMENT
        actor_id = participant.actor.department_id
    return FindingParticipantResponse(
        finding_id=participant.finding_id,
        actor_kind=actor_kind,
        actor_id=actor_id,
        role_key=participant.role_key,
        assigned_at=participant.assigned_at,
    )


def _raise_api_error(exc: Exception) -> NoReturn:
    if isinstance(exc, IntegrityError):
        raise_database_conflict(exc)
    if isinstance(exc, ReviewAuthorizationError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(
        exc,
        (ConcurrentCaseTransitionError, ConcurrentFindingTransitionError),
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unexpected Finding operation failure",
    ) from exc


@review_findings_router.post(
    "/review-cases/{case_id}/findings",
    response_model=FindingResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createFinding",
)
def create_finding(
    case_id: UUID,
    payload: FindingCreateRequest,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> FindingResponse:
    service = build_finding_lifecycle_service(session)
    try:
        finding = service.create_finding(
            identity.user,
            ReviewCaseId(case_id),
            payload.title,
            payload.severity,
            payload.scenario_data,
            description=payload.description,
        )
    except (
        ConcurrentCaseTransitionError,
        ReviewAuthorizationError,
        LookupError,
        ValueError,
        IntegrityError,
    ) as exc:
        _raise_api_error(exc)
    return _finding_response(finding)


@review_findings_router.get(
    "/review-cases/{case_id}/findings",
    response_model=list[FindingResponse],
    operation_id="listFindings",
)
def list_findings(
    case_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[FindingResponse]:
    service = build_finding_lifecycle_service(session)
    try:
        findings = service.list_findings(identity.user, ReviewCaseId(case_id))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return [_finding_response(finding) for finding in findings]


@review_findings_router.get(
    "/findings/{finding_id}",
    response_model=FindingResponse,
    operation_id="getFinding",
)
def get_finding(
    finding_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> FindingResponse:
    service = build_finding_lifecycle_service(session)
    try:
        finding = service.get_finding(identity.user, FindingId(finding_id))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return _finding_response(finding)


@review_findings_router.get(
    "/findings/{finding_id}/participants",
    response_model=list[FindingParticipantResponse],
    operation_id="listFindingParticipants",
)
def list_finding_participants(
    finding_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[FindingParticipantResponse]:
    service = build_finding_lifecycle_service(session)
    try:
        participants = service.list_participants(identity.user, FindingId(finding_id))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return [_participant_response(participant) for participant in participants]


@review_findings_router.post(
    "/findings/{finding_id}/participants",
    response_model=FindingParticipantResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="addFindingParticipant",
)
def add_finding_participant(
    finding_id: UUID,
    payload: FindingParticipantCreateRequest,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> FindingParticipantResponse:
    participant_actor = (
        UserActor(UserId(payload.actor_id))
        if payload.actor_kind is ActorKind.USER
        else DepartmentActor(DepartmentId(payload.actor_id))
    )
    service = build_finding_lifecycle_service(session)
    notifications = build_notification_orchestrator(session)
    try:
        result = service.add_participant_result(
            identity.user,
            FindingId(finding_id),
            participant_actor,
            payload.role_key,
        )
        notifications.finding_participant_added(result)
    except (
        ConcurrentCaseTransitionError,
        ConcurrentFindingTransitionError,
        ReviewAuthorizationError,
        LookupError,
        ValueError,
        IntegrityError,
    ) as exc:
        _raise_api_error(exc)
    return _participant_response(result.participant)


@review_findings_router.post(
    "/findings/{finding_id}/transitions",
    response_model=FindingResponse,
    operation_id="transitionFinding",
)
def transition_finding(
    finding_id: UUID,
    payload: FindingTransitionRequest,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> FindingResponse:
    service = build_finding_lifecycle_service(session)
    try:
        finding = service.transition_finding(
            identity.user,
            FindingId(finding_id),
            payload.action,
            reason=payload.reason,
        )
    except (
        ConcurrentCaseTransitionError,
        ConcurrentFindingTransitionError,
        ReviewAuthorizationError,
        LookupError,
        ValueError,
        IntegrityError,
    ) as exc:
        _raise_api_error(exc)
    return _finding_response(finding)
