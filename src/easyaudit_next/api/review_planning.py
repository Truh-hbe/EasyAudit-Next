from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from easyaudit_next.api.dependencies import BusinessIdentity, DatabaseSession
from easyaudit_next.api.review_contracts import (
    CaseMemberCandidateResponse,
    CaseMemberCreateRequest,
    CaseMemberResponse,
    ReviewCaseCollectionResponse,
    ReviewCaseCreateRequest,
    ReviewCaseResponse,
    ReviewCaseTransitionRequest,
    ReviewCatalogItemResponse,
    ReviewPlanCreateRequest,
    ReviewPlanResponse,
)
from easyaudit_next.composition import (
    build_case_team_coordinator,
    build_notification_orchestrator,
    build_review_case_collection_query_service,
    build_review_case_context_query_service,
    build_review_catalog_query_service,
    build_review_planning_service,
)
from easyaudit_next.platform.domain.ids import UserId
from easyaudit_next.platform.domain.models import User
from easyaudit_next.review_case_queries.context_service import (
    CaseMemberView,
    ReviewCaseActivityView,
)
from easyaudit_next.review_case_queries.schemas import (
    CaseMemberViewResponse,
    ReviewCaseActivityResponse,
)
from easyaudit_next.review_core.application.review_planning import (
    CaseManagerConflictError,
    ConcurrentCaseTransitionError,
    ReviewAuthorizationError,
)
from easyaudit_next.review_core.domain.ids import ReviewCaseId, ReviewPlanId
from easyaudit_next.review_core.domain.models import (
    CaseMember,
    ReviewCase,
    ReviewPlan,
    ScenarioKey,
    ScenarioVersion,
)

review_planning_router = APIRouter(prefix="/api/v1", tags=["review-planning"])


def _plan_response(plan: ReviewPlan) -> ReviewPlanResponse:
    return ReviewPlanResponse(
        id=plan.id,
        organization_id=plan.organization_id,
        title=plan.title,
        planned_start_at=plan.planned_start_at,
        planned_end_at=plan.planned_end_at,
        created_by=plan.created_by,
    )


def _case_response(review_case: ReviewCase) -> ReviewCaseResponse:
    return ReviewCaseResponse(
        id=review_case.id,
        organization_id=review_case.organization_id,
        plan_id=review_case.plan_id,
        scenario_key=review_case.scenario_key,
        scenario_version=review_case.scenario_version,
        title=review_case.title,
        lifecycle=review_case.lifecycle,
        planned_start_at=review_case.planned_start_at,
        planned_end_at=review_case.planned_end_at,
        started_at=review_case.started_at,
        fieldwork_completed_at=review_case.fieldwork_completed_at,
        closed_at=review_case.closed_at,
        scenario_data=dict(review_case.scenario_data),
        created_by=review_case.created_by,
        created_at=review_case.created_at,
    )


def _member_response(member: CaseMember) -> CaseMemberResponse:
    return CaseMemberResponse(
        case_id=member.case_id,
        user_id=member.user_id,
        role_key=member.role_key,
        joined_at=member.joined_at,
    )


def _member_candidate_response(user: User) -> CaseMemberCandidateResponse:
    return CaseMemberCandidateResponse(user_id=user.id, display_name=user.display_name)


def _member_view_response(member: CaseMemberView) -> CaseMemberViewResponse:
    return CaseMemberViewResponse(
        case_id=member.case_id,
        user_id=member.user_id,
        role_key=member.role_key,
        joined_at=member.joined_at,
        display_name=member.display_name,
    )


def _activity_response(activity: ReviewCaseActivityView) -> ReviewCaseActivityResponse:
    return ReviewCaseActivityResponse(
        id=activity.id,
        subject_id=activity.subject_id,
        event_type=activity.event_type,
        actor_id=activity.actor_id,
        occurred_at=activity.occurred_at,
    )


def _raise_api_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ReviewAuthorizationError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(
        exc,
        (CaseManagerConflictError, ConcurrentCaseTransitionError, IntegrityError),
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unexpected review planning failure",
    ) from exc


@review_planning_router.post(
    "/review-plans",
    response_model=ReviewPlanResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createReviewPlan",
)
def create_review_plan(
    payload: ReviewPlanCreateRequest,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> ReviewPlanResponse:
    service = build_review_planning_service(session)
    try:
        plan = service.create_plan(
            identity.user,
            payload.title,
            planned_start_at=payload.planned_start_at,
            planned_end_at=payload.planned_end_at,
        )
    except (ReviewAuthorizationError, ValueError, IntegrityError) as exc:
        _raise_api_error(exc)
    return _plan_response(plan)


@review_planning_router.get(
    "/review-catalog",
    response_model=list[ReviewCatalogItemResponse],
    operation_id="listReviewCatalog",
)
def list_review_catalog(
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[ReviewCatalogItemResponse]:
    items = build_review_catalog_query_service(session).list_creatable(identity.user)
    return [
        ReviewCatalogItemResponse(
            scenario_key=item.scenario_key,
            scenario_version=item.scenario_version,
            display_name=item.display_name,
        )
        for item in items
    ]


@review_planning_router.get(
    "/review-plans",
    response_model=list[ReviewPlanResponse],
    operation_id="listReviewPlans",
)
def list_review_plans(
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[ReviewPlanResponse]:
    service = build_review_planning_service(session)
    try:
        return [_plan_response(item) for item in service.list_plans(identity.user)]
    except ReviewAuthorizationError as exc:
        _raise_api_error(exc)


@review_planning_router.get(
    "/review-plans/{plan_id}",
    response_model=ReviewPlanResponse,
    operation_id="getReviewPlan",
)
def get_review_plan(
    plan_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> ReviewPlanResponse:
    service = build_review_planning_service(session)
    try:
        return _plan_response(service.get_plan(identity.user, ReviewPlanId(plan_id)))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)


@review_planning_router.post(
    "/review-cases",
    response_model=ReviewCaseResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createReviewCase",
)
def create_review_case(
    payload: ReviewCaseCreateRequest,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> ReviewCaseResponse:
    try:
        review_case = build_case_team_coordinator(session).create_case(
            identity.user,
            ScenarioKey(payload.scenario_key),
            ScenarioVersion(payload.scenario_version),
            payload.title,
            payload.scenario_data,
            plan_id=ReviewPlanId(payload.plan_id) if payload.plan_id is not None else None,
            planned_start_at=payload.planned_start_at,
            planned_end_at=payload.planned_end_at,
        )
    except (
        CaseManagerConflictError,
        ReviewAuthorizationError,
        LookupError,
        ValueError,
        IntegrityError,
    ) as exc:
        _raise_api_error(exc)
    return _case_response(review_case)


@review_planning_router.get(
    "/review-cases",
    response_model=ReviewCaseCollectionResponse,
    operation_id="listReviewCases",
)
def list_review_cases(
    identity: BusinessIdentity,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReviewCaseCollectionResponse:
    collection = build_review_case_collection_query_service(session).list_review_cases(
        identity.user,
        limit=limit,
        offset=offset,
    )
    return ReviewCaseCollectionResponse(
        items=tuple(_case_response(item) for item in collection.items),
        total=collection.total,
        limit=collection.limit,
        offset=collection.offset,
    )


@review_planning_router.get(
    "/review-cases/{case_id}",
    response_model=ReviewCaseResponse,
    operation_id="getReviewCase",
)
def get_review_case(
    case_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> ReviewCaseResponse:
    service = build_review_planning_service(session)
    try:
        return _case_response(service.get_case(identity.user, ReviewCaseId(case_id)))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)


@review_planning_router.get(
    "/review-cases/{case_id}/members",
    response_model=list[CaseMemberViewResponse],
    operation_id="listReviewCaseMembers",
)
def list_review_case_members(
    case_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[CaseMemberViewResponse]:
    service = build_review_case_context_query_service(session)
    try:
        members = service.list_member_views(identity.user, ReviewCaseId(case_id))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return [_member_view_response(member) for member in members]


@review_planning_router.get(
    "/review-cases/{case_id}/member-candidates",
    response_model=list[CaseMemberCandidateResponse],
    operation_id="listReviewCaseMemberCandidates",
)
def list_review_case_member_candidates(
    case_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
    role_key: Annotated[str, Query(min_length=1, max_length=100)],
    q: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
) -> list[CaseMemberCandidateResponse]:
    service = build_review_planning_service(session)
    try:
        candidates = service.list_case_member_candidates(
            identity.user,
            ReviewCaseId(case_id),
            role_key,
            query=q,
            limit=limit,
        )
    except (ReviewAuthorizationError, LookupError, ValueError) as exc:
        _raise_api_error(exc)
    return [_member_candidate_response(user) for user in candidates]


@review_planning_router.get(
    "/review-cases/{case_id}/activities",
    response_model=list[ReviewCaseActivityResponse],
    operation_id="listReviewCaseActivities",
)
def list_review_case_activities(
    case_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[ReviewCaseActivityResponse]:
    service = build_review_case_context_query_service(session)
    try:
        activities = service.list_case_activities(identity.user, ReviewCaseId(case_id))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return [_activity_response(activity) for activity in activities]


@review_planning_router.post(
    "/review-cases/{case_id}/members",
    response_model=CaseMemberResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="addReviewCaseMember",
)
def add_review_case_member(
    case_id: UUID,
    payload: CaseMemberCreateRequest,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> CaseMemberResponse:
    coordinator = build_case_team_coordinator(session)
    notifications = build_notification_orchestrator(session)
    try:
        result = coordinator.add_case_member_result(
            identity.user,
            ReviewCaseId(case_id),
            UserId(payload.user_id),
            payload.role_key,
        )
        notifications.case_member_added(result)
    except (ReviewAuthorizationError, LookupError, ValueError, IntegrityError) as exc:
        _raise_api_error(exc)
    return _member_response(result.member)


@review_planning_router.delete(
    "/review-cases/{case_id}/members/{user_id}",
    response_model=CaseMemberResponse,
    operation_id="removeReviewCaseMember",
)
def remove_review_case_member(
    case_id: UUID,
    user_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
    role_key: Annotated[str, Query(min_length=1, max_length=100)],
) -> CaseMemberResponse:
    try:
        result = build_case_team_coordinator(session).remove_case_member_result(
            identity.user,
            ReviewCaseId(case_id),
            UserId(user_id),
            role_key,
        )
    except (
        CaseManagerConflictError,
        ReviewAuthorizationError,
        LookupError,
        ValueError,
        IntegrityError,
    ) as exc:
        _raise_api_error(exc)
    return _member_response(result.member)


@review_planning_router.post(
    "/review-cases/{case_id}/transitions",
    response_model=ReviewCaseResponse,
    operation_id="transitionReviewCase",
)
def transition_review_case(
    case_id: UUID,
    payload: ReviewCaseTransitionRequest,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> ReviewCaseResponse:
    service = build_review_planning_service(session)
    try:
        review_case = service.transition_case(
            identity.user,
            ReviewCaseId(case_id),
            payload.action,
            reason=payload.reason,
        )
    except (
        ConcurrentCaseTransitionError,
        ReviewAuthorizationError,
        LookupError,
        ValueError,
        IntegrityError,
    ) as exc:
        _raise_api_error(exc)
    return _case_response(review_case)
