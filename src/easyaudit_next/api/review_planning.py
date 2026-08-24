from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from easyaudit_next.api.dependencies import BusinessIdentity, DatabaseSession
from easyaudit_next.api.review_contracts import (
    CaseMemberCreateRequest,
    CaseMemberResponse,
    ReviewCaseCreateRequest,
    ReviewCaseResponse,
    ReviewCaseTransitionRequest,
    ReviewPlanCreateRequest,
    ReviewPlanResponse,
)
from easyaudit_next.composition import build_review_planning_service
from easyaudit_next.platform.domain.ids import UserId
from easyaudit_next.review_core.application.review_planning import (
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


def _raise_api_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ReviewAuthorizationError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


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
    service = build_review_planning_service(session)
    try:
        review_case = service.create_case(
            identity.user,
            ScenarioKey(payload.scenario_key),
            ScenarioVersion(payload.scenario_version),
            payload.title,
            payload.scenario_data,
            plan_id=ReviewPlanId(payload.plan_id) if payload.plan_id is not None else None,
            planned_start_at=payload.planned_start_at,
            planned_end_at=payload.planned_end_at,
        )
    except (ReviewAuthorizationError, LookupError, ValueError, IntegrityError) as exc:
        _raise_api_error(exc)
    return _case_response(review_case)


@review_planning_router.get(
    "/review-cases",
    response_model=list[ReviewCaseResponse],
    operation_id="listReviewCases",
)
def list_review_cases(
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[ReviewCaseResponse]:
    service = build_review_planning_service(session)
    try:
        return [_case_response(item) for item in service.list_cases(identity.user)]
    except ReviewAuthorizationError as exc:
        _raise_api_error(exc)


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
    response_model=list[CaseMemberResponse],
    operation_id="listReviewCaseMembers",
)
def list_review_case_members(
    case_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> list[CaseMemberResponse]:
    service = build_review_planning_service(session)
    try:
        members = service.list_case_members(identity.user, ReviewCaseId(case_id))
    except (ReviewAuthorizationError, LookupError) as exc:
        _raise_api_error(exc)
    return [_member_response(member) for member in members]


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
    service = build_review_planning_service(session)
    try:
        member = service.add_case_member(
            identity.user,
            ReviewCaseId(case_id),
            UserId(payload.user_id),
            payload.role_key,
        )
    except (ReviewAuthorizationError, LookupError, ValueError, IntegrityError) as exc:
        _raise_api_error(exc)
    return _member_response(member)


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
