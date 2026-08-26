from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from easyaudit_next.api.dependencies import BusinessIdentity, DatabaseSession
from easyaudit_next.api.review_contracts import FindingResponse, SubmissionResponse
from easyaudit_next.api.review_verification_contracts import (
    FindingReopenRequest,
    VerificationSubmissionRequest,
    VerificationSubmissionResponse,
)
from easyaudit_next.composition import build_verification_closure_service
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
)
from easyaudit_next.review_core.application.review_planning import (
    ConcurrentCaseTransitionError,
    ReviewAuthorizationError,
)
from easyaudit_next.review_core.domain.ids import FindingId
from easyaudit_next.review_core.domain.models import Finding, Submission

review_verification_router = APIRouter(prefix="/api/v1", tags=["review-verification"])


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
        (ConcurrentCaseTransitionError, ConcurrentFindingTransitionError, IntegrityError),
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unexpected verification operation failure",
    ) from exc


@review_verification_router.post(
    "/findings/{finding_id}/verification-submissions",
    response_model=VerificationSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="submitFindingVerification",
)
def submit_finding_verification(
    finding_id: UUID,
    payload: VerificationSubmissionRequest,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> VerificationSubmissionResponse:
    service = build_verification_closure_service(session)
    try:
        submission, finding = service.submit_verification(
            identity.user,
            FindingId(finding_id),
            payload.action,
            payload.payload,
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
    return VerificationSubmissionResponse(
        submission=_submission_response(submission),
        finding=_finding_response(finding),
    )


@review_verification_router.post(
    "/findings/{finding_id}/reopen",
    response_model=FindingResponse,
    operation_id="reopenFinding",
)
def reopen_finding(
    finding_id: UUID,
    payload: FindingReopenRequest,
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> FindingResponse:
    service = build_verification_closure_service(session)
    try:
        finding = service.reopen_finding(
            identity.user,
            FindingId(finding_id),
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
