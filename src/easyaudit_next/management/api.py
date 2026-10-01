from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from easyaudit_next.api.dependencies import BusinessIdentity, DatabaseSession
from easyaudit_next.composition import build_management_query_service
from easyaudit_next.infrastructure.database import snapshot_read
from easyaudit_next.management.schemas import (
    ManagementCaseCollectionResponse,
    ManagementCaseProgressResponse,
    ManagementDeadlineFilter,
)
from easyaudit_next.review_core.domain.models import ReviewCaseLifecycle

management_router = APIRouter(prefix="/api/v1/management", tags=["management"])


@management_router.get(
    "/review-cases",
    response_model=ManagementCaseCollectionResponse,
    operation_id="listManagedReviewCases",
)
def list_managed_review_cases(
    identity: BusinessIdentity,
    session: DatabaseSession,
    review_plan_id: UUID | None = None,
    lifecycle: ReviewCaseLifecycle | None = None,
    deadline_status: ManagementDeadlineFilter = ManagementDeadlineFilter.ALL,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ManagementCaseCollectionResponse:
    with snapshot_read(session):
        return build_management_query_service(session).list_review_cases(
            identity.user,
            review_plan_id=review_plan_id,
            lifecycle=lifecycle,
            deadline_status=deadline_status,
            limit=limit,
            offset=offset,
        )


@management_router.get(
    "/review-cases/{case_id}/progress",
    response_model=ManagementCaseProgressResponse,
    operation_id="getManagedReviewCaseProgress",
)
def get_managed_review_case_progress(
    case_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> ManagementCaseProgressResponse:
    try:
        with snapshot_read(session):
            return build_management_query_service(session).get_progress(identity.user, case_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ReviewCase not found",
        ) from exc
