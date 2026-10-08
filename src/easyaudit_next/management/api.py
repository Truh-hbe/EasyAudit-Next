from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Response, status

from easyaudit_next.api.dependencies import BusinessIdentity, DatabaseSession
from easyaudit_next.composition import build_management_query_service
from easyaudit_next.infrastructure.database import snapshot_read
from easyaudit_next.infrastructure.observability import APP_LOGGER
from easyaudit_next.management.export import (
    XLSX_MEDIA_TYPE,
    ExportFormat,
    render_export,
)
from easyaudit_next.management.schemas import (
    ManagementCaseCollectionResponse,
    ManagementCaseFilters,
    ManagementCaseProgressResponse,
    ManagementDeadlineFilter,
)
from easyaudit_next.platform.settings import get_settings
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
    "/review-cases/export",
    response_class=Response,
    operation_id="exportManagedReviewCases",
    responses={
        status.HTTP_200_OK: {
            "description": "Snapshot of all authorized rows matching the filters.",
            "content": {
                "text/csv": {"schema": {"type": "string", "format": "binary"}},
                XLSX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}},
            },
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Invalid request, or the filtered row count exceeds EXPORT_MAX_ROWS."
        },
    },
)
def export_managed_review_cases(
    identity: BusinessIdentity,
    session: DatabaseSession,
    format: ExportFormat,
    review_plan_id: UUID | None = None,
    lifecycle: ReviewCaseLifecycle | None = None,
    deadline_status: ManagementDeadlineFilter = ManagementDeadlineFilter.ALL,
) -> Response:
    settings = get_settings()
    with snapshot_read(session):
        snapshot = build_management_query_service(session).export_review_cases(
            identity.user,
            ManagementCaseFilters(
                review_plan_id=review_plan_id,
                lifecycle=lifecycle,
                deadline_status=deadline_status,
            ),
            max_rows=settings.export_max_rows,
        )
    document = render_export(
        snapshot,
        format,
        generated_at=datetime.now(UTC),
        tz=ZoneInfo(settings.export_timezone),
    )
    # Data leaves the system: record who exported what volume. Counts and format only.
    log_fields = {
        "export_format": format.value,
        "row_count": len(snapshot.items),
        "organization_id": str(identity.user.organization_id),
        "actor_user_id": str(identity.user.id),
    }
    APP_LOGGER.info("management_export", extra={"fields": log_fields})
    return Response(
        content=document.content,
        media_type=document.media_type,
        headers={
            "Content-Disposition": document.content_disposition,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
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
