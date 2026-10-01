"""Evidence download: authorize in a short transaction, then stream the object.

`GET /api/v1/evidences/{id}/content` looks the Evidence up by `(organization, id)` and applies
the same read permission as listing the Action's Evidence. Missing, foreign and forbidden are one
404, and none of them touches the object store. The transaction ends (commit, connection back to
the pool) before the store is contacted, and the response object opens the object itself, so by
the time the first byte is sent every dependency, including the DB session, has been released.

The download does not recompute the sha256: that would read the whole object twice per request.
Integrity is checked out of band by `easyaudit-next verify-evidence`.
"""

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect
from starlette.responses import Response, StreamingResponse
from starlette.types import Receive, Scope, Send

from easyaudit_next.api.dependencies import BusinessIdentity, DatabaseSession
from easyaudit_next.api.review_evidence_uploads import get_evidence_object_store
from easyaudit_next.composition import build_rectification_service
from easyaudit_next.infrastructure.observability import (
    APP_LOGGER,
    current_request_id,
    describe_exception,
)
from easyaudit_next.platform.domain.models import User
from easyaudit_next.review_core.application.evidence_policy import download_content_type
from easyaudit_next.review_core.application.evidence_storage import (
    EvidenceObjectStore,
    ObjectNotFoundError,
    ObjectStoreError,
)
from easyaudit_next.review_core.application.review_planning import ReviewAuthorizationError
from easyaudit_next.review_core.domain.ids import EvidenceId
from easyaudit_next.review_core.domain.models import Evidence

review_evidence_download_router = APIRouter(prefix="/api/v1", tags=["review-rectification"])

_FALLBACK_UNSAFE = frozenset('"\\;%')


def content_disposition(original_name: str) -> str:
    """`attachment` with an ASCII `filename` for old clients and an RFC 5987 `filename*` that
    carries the real (UTF-8, percent-encoded) name."""
    fallback = "".join(
        "_" if not (" " <= ch <= "~") or ch in _FALLBACK_UNSAFE else ch for ch in original_name
    )
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(original_name, safe='')}"


def _download_headers(evidence: Evidence) -> dict[str, str]:
    return {
        "Content-Type": download_content_type(evidence.content_type),
        "Content-Length": str(evidence.size_bytes),
        "Content-Disposition": content_disposition(evidence.original_name),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }


class EvidenceDownloadResponse(Response):
    """Opens the object when the response is sent, streams it, and always closes it: on
    completion, on a client disconnect (either ASGI flavour), on cancellation and on error."""

    def __init__(self, store: EvidenceObjectStore, evidence: Evidence) -> None:
        self._store = store
        self._evidence = evidence
        self.status_code = 200
        self.background = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        evidence = self._evidence
        evidence_id = f"{evidence.id}"  # computed here: log calls take constants and names only
        try:
            stream = await self._store.open_stream(evidence.storage_key)
        except ObjectNotFoundError as exc:
            # Metadata without bytes is Evidence loss (a pilot stop condition): it must be
            # loud, so it is a 500 and an ERROR log, never a 404.
            APP_LOGGER.error(
                "evidence_object_missing",
                extra={
                    "fields": {
                        "evidence_id": evidence_id,
                        "storage_key": evidence.storage_key,
                    },
                    "exception_details": describe_exception(exc),
                },
            )
            await JSONResponse(
                {"detail": "Evidence file is unavailable", "request_id": current_request_id()},
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )(scope, receive, send)
            return
        except ObjectStoreError as exc:
            APP_LOGGER.warning(
                "object_storage_operation_failed",
                extra={
                    "fields": {"component": "object_storage", "reason": "get_failed"},
                    "exception_details": describe_exception(exc),
                },
            )
            await JSONResponse(
                {"detail": "Evidence storage is not available"},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )(scope, receive, send)
            return
        try:
            await StreamingResponse(stream, headers=_download_headers(evidence))(
                scope, receive, send
            )
        except ClientDisconnect:
            pass  # the client went away; nothing to report and nobody to answer
        finally:
            await stream.aclose()


def _authorize(session: Session, actor: User, evidence_id: EvidenceId) -> Evidence:
    evidence = build_rectification_service(session).get_evidence_for_download(actor, evidence_id)
    session.commit()  # ends the read transaction before any byte is streamed
    session.expunge_all()
    return evidence


@review_evidence_download_router.get(
    "/evidences/{evidence_id}/content",
    operation_id="downloadEvidenceContent",
    response_class=Response,
    responses={
        200: {
            "description": "The file's bytes as an attachment",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        },
        404: {"description": "Not found, or not visible to this user"},
        500: {"description": "Metadata exists but the object is missing (Evidence loss)"},
        503: {"description": "Object storage is not available"},
    },
)
async def download_evidence_content(
    evidence_id: UUID,
    identity: BusinessIdentity,
    session: DatabaseSession,
    store: Annotated[EvidenceObjectStore, Depends(get_evidence_object_store)],
) -> Response:
    try:
        evidence = await run_in_threadpool(
            _authorize, session, identity.user, EvidenceId(evidence_id)
        )
    except (ReviewAuthorizationError, LookupError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found"
        ) from exc
    return EvidenceDownloadResponse(store, evidence)
