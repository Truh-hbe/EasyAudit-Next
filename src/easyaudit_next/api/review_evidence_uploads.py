"""Evidence upload: the raw request body is streamed to object storage, then registered.

Phases (the transaction boundaries are the point of this module):

1. Pre-authorization in a short transaction that is committed *before* the first body byte is
   read. Nothing is locked, and no transaction is open while the upload runs: a long upload
   must not trip `idle_in_transaction_session_timeout` or pin a pooled connection.
2. Stream the body to the object store under a server-generated key, hashing and counting on
   the way. The size limit is enforced twice: on `Content-Length` before reading, and on the
   running total while reading.
3. A new short transaction calls `register_evidence`, which authorizes again, locks the
   Finding, and writes the metadata and the Activity with the *server-computed* key, size and
   sha256. If it fails, the object is deleted (best effort) and the original error is returned.
"""

import asyncio
from collections.abc import Callable
from functools import partial
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import ClientDisconnect

from easyaudit_next.api.dependencies import (
    BusinessIdentity,
    DatabaseSession,
    get_session_factory,
)
from easyaudit_next.api.review_contracts import EvidenceResponse
from easyaudit_next.api.review_rectification import _evidence_response, _raise_api_error
from easyaudit_next.composition import (
    build_evidence_upload_policy,
    build_rectification_service,
)
from easyaudit_next.infrastructure.observability import APP_LOGGER, describe_exception
from easyaudit_next.platform.domain.ids import UserId
from easyaudit_next.platform.domain.models import User
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.platform.settings import get_settings
from easyaudit_next.review_core.application.evidence_policy import (
    EvidenceUploadPolicy,
    InvalidEvidenceFilenameError,
    UnsupportedEvidenceTypeError,
    ValidatedEvidenceFile,
)
from easyaudit_next.review_core.application.evidence_storage import (
    EvidenceObjectStore,
    EvidenceTooLargeError,
    ObjectStoreError,
    limit_stream,
    new_storage_key,
)
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
)
from easyaudit_next.review_core.application.review_planning import (
    ConcurrentCaseTransitionError,
    ReviewAuthorizationError,
)
from easyaudit_next.review_core.domain.ids import ActionItemId
from easyaudit_next.review_core.domain.models import Evidence

review_evidence_upload_router = APIRouter(prefix="/api/v1", tags=["review-rectification"])

_BUSINESS_ERRORS = (
    ConcurrentCaseTransitionError,
    ConcurrentFindingTransitionError,
    ReviewAuthorizationError,
    LookupError,
    ValueError,
    IntegrityError,
)


def get_evidence_object_store(request: Request) -> EvidenceObjectStore:
    store: EvidenceObjectStore | None = getattr(request.app.state, "evidence_store", None)
    if store is None:  # set by the lifespan; None = object storage is not configured
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Evidence storage is not available",
        )
    return store


def get_evidence_upload_policy() -> EvidenceUploadPolicy:
    return build_evidence_upload_policy(get_settings())


EvidenceStore = Annotated[EvidenceObjectStore, Depends(get_evidence_object_store)]
UploadPolicy = Annotated[EvidenceUploadPolicy, Depends(get_evidence_upload_policy)]


def _preauthorize(session: Session, actor: User, action_item_id: ActionItemId) -> None:
    build_rectification_service(session).authorize_evidence_registration(actor, action_item_id)
    session.commit()  # ends the read transaction; the connection goes back to the pool
    session.expunge_all()  # the registration transaction must not see this phase's snapshots


class RegistrationOutcomeUnknown(Exception):
    """COMMIT itself failed, so the transaction may or may not have been applied. The object
    must then be kept: deleting it could leave metadata without bytes."""


def _log_cleanup_failure(exc: Exception) -> None:
    APP_LOGGER.warning(
        "evidence_session_cleanup_failed", extra={"exception_details": describe_exception(exc)}
    )


def _quietly(action: Callable[[], object]) -> None:
    try:
        action()
    except Exception as exc:  # best-effort cleanup must not replace the outcome being reported
        _log_cleanup_failure(exc)


def _register(
    session_factory: sessionmaker[Session],
    actor_id: UserId,
    action_item_id: ActionItemId,
    key: str,
    file: ValidatedEvidenceFile,
    size_bytes: int,
    sha256: str,
    description: str | None,
) -> Evidence:
    """Runs in a worker thread that cannot be stopped, so it owns its Session: created, committed
    or rolled back, and closed here, never touched by the request that started it."""
    session = session_factory()
    try:
        try:
            # A fresh read: the actor may have been deactivated while the file was uploading.
            actor = SqlAlchemyUserRepository(session).get(actor_id)
            if actor is None:
                raise ReviewAuthorizationError("Active organization user required")
            evidence = build_rectification_service(session).register_evidence(
                actor,
                action_item_id,
                key,
                file.original_name,
                size_bytes,
                sha256,
                content_type=file.content_type,
                description=description,
            )
        except BaseException:
            _quietly(session.rollback)
            raise
        try:
            session.commit()
        except BaseException as exc:
            # Whatever the rollback does, the outcome of COMMIT is unknown.
            _quietly(session.rollback)
            raise RegistrationOutcomeUnknown from exc
        return evidence
    finally:
        _quietly(session.close)


async def _discard_object(store: EvidenceObjectStore, key: str) -> None:
    """Best effort. An object that cannot be deleted is an orphan for the Pilot-4B cleanup."""
    try:
        await asyncio.shield(store.delete(key))
    except Exception as exc:
        APP_LOGGER.warning(
            "evidence_object_orphaned",
            extra={"fields": {"storage_key": key}, "exception_details": describe_exception(exc)},
        )


def _consume(task: "asyncio.Future[Evidence]") -> None:
    if not task.cancelled():
        task.exception()  # retrieved: an abandoned registration reports through its outcome


async def _register_and_settle(
    store: EvidenceObjectStore,
    key: str,
    register: Callable[[], Evidence],
    wait_limit_seconds: float,
) -> Evidence:
    """Run the registration and decide the object's fate from its definite outcome.

    The registration runs in a worker thread that cannot be stopped, so cancelling this request
    must not be taken as "the registration did not happen": the task is shielded and, after a
    cancellation, awaited for at most `wait_limit_seconds`. Committed -> keep the object.
    Rolled back -> delete it. Commit outcome unknown, or no outcome within the limit -> keep it
    (the thread runs on by itself; the worst case is an orphan for Pilot-4B). A cancellation is
    re-raised afterwards. Metadata without an object is never produced.
    """
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(run_in_threadpool(register))
    task.add_done_callback(_consume)
    cancelled = False
    deadline: float | None = None
    while not task.done():
        timeout = None if deadline is None else deadline - loop.time()
        if timeout is not None and timeout <= 0:
            break
        try:
            await asyncio.wait({task}, timeout=timeout)
        except asyncio.CancelledError:
            cancelled = True
            if deadline is None:
                deadline = loop.time() + wait_limit_seconds
    if not task.done():
        APP_LOGGER.warning(
            "evidence_registration_unsettled", extra={"fields": {"storage_key": key}}
        )
        raise asyncio.CancelledError
    error = task.exception()
    if error is None:
        if cancelled:
            raise asyncio.CancelledError
        return task.result()
    if isinstance(error, RegistrationOutcomeUnknown):
        APP_LOGGER.warning(
            "evidence_registration_outcome_unknown",
            extra={"fields": {"storage_key": key}, "exception_details": describe_exception(error)},
        )
        error = error.__cause__ or error
    else:
        try:
            await _discard_object(store, key)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    if isinstance(error, _BUSINESS_ERRORS):
        _raise_api_error(error)
    raise error


def _settle_wait_limit_seconds() -> float:
    """How long a cancelled request waits for its registration before treating the outcome as
    unknown: the longest a statement can run plus the longest a lock can be awaited, plus slack."""
    settings = get_settings()
    return (settings.db_statement_timeout_ms + settings.db_lock_timeout_ms) / 1000 + 5


def _too_large(max_bytes: int) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"Evidence exceeds the maximum size of {max_bytes} bytes",
    )


def _declared_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    return int(raw) if raw is not None and raw.isdigit() else None


@review_evidence_upload_router.post(
    "/action-items/{action_item_id}/evidence-uploads",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="uploadActionEvidence",
    responses={
        413: {"description": "Evidence exceeds EVIDENCE_MAX_BYTES"},
        415: {"description": "Content type not allowed, or extension does not match it"},
        503: {"description": "Object storage is not available"},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "description": (
                "The file's raw bytes (not multipart). `Content-Type` is the file type; the "
                "original name goes in `X-Evidence-Filename` as percent-encoded UTF-8."
            ),
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload_action_evidence(
    action_item_id: UUID,
    request: Request,
    identity: BusinessIdentity,
    session: DatabaseSession,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    store: EvidenceStore,
    policy: UploadPolicy,
    filename: Annotated[str, Header(alias="X-Evidence-Filename", min_length=1, max_length=2048)],
    description: Annotated[str | None, Query(max_length=1000)] = None,
) -> EvidenceResponse:
    action_id = ActionItemId(action_item_id)
    try:
        await run_in_threadpool(_preauthorize, session, identity.user, action_id)
    except _BUSINESS_ERRORS as exc:
        _raise_api_error(exc)

    try:
        file = policy.validate(request.headers.get("content-type"), filename)
    except UnsupportedEvidenceTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    except InvalidEvidenceFilenameError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    declared = _declared_length(request)
    if declared is not None and declared > policy.max_bytes:
        _too_large(policy.max_bytes)
    if declared == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Evidence file is empty"
        )

    key = new_storage_key(identity.user.organization_id)
    try:
        stored = await store.put_stream(key, limit_stream(request.stream(), policy.max_bytes))
    except EvidenceTooLargeError:
        _too_large(policy.max_bytes)
    except ClientDisconnect as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Upload was interrupted"
        ) from exc
    except ObjectStoreError as exc:
        APP_LOGGER.warning(
            "object_storage_operation_failed",
            extra={
                "fields": {"component": "object_storage", "reason": "put_failed"},
                "exception_details": describe_exception(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Evidence storage is not available",
        ) from exc

    if stored.size_bytes == 0:
        await _discard_object(store, key)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Evidence file is empty"
        )
    evidence = await _register_and_settle(
        store,
        key,
        partial(
            _register,
            session_factory,
            identity.user.id,
            action_id,
            key,
            file,
            stored.size_bytes,
            stored.sha256,
            description,
        ),
        _settle_wait_limit_seconds(),
    )
    return _evidence_response(evidence)
