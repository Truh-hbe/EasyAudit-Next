"""Operator commands over Evidence objects: orphan cleanup and integrity verification.

Both run outside request handling (`easyaudit-next cleanup-evidence-orphans`,
`verify-evidence`) and never hold a database transaction while talking to the object store.

Orphans: an object under `org/<id>/evidence/` that no `evidences.storage_key` references. They
appear when an upload's registration fails and the best-effort delete fails too, when a
registration commit outcome was unknown, and after a restore (the bucket mirror is taken after
the database dump, so it is a superset of what the restored database references). An object is
deleted only if it is unreferenced, older than `min_age`, and *still* unreferenced when
re-checked in a fresh transaction right before its delete. `min_age` is what protects uploads in
flight and registrations that a stuck worker thread commits late; the re-check closes the window
between "listed" and "deleted". An object that is referenced is never deleted.

A delete run is also refused as a whole, before anything is deleted or aborted, when the
database looks wrong (a wrong or half-restored one would turn every old object into an
"orphan"): no Evidence rows at all while objects exist, a schema revision that is not this
code's head, or more deletions planned than `max_delete`. A refusal is a non-zero exit with the
reason in the result; the operator looks, then reruns (raising `--max-delete` if the number is
really expected). All of that is decided on the *complete* candidate set, after the whole
listing and before the first delete. Dry runs do not evaluate the guards.

Known, accepted window (pilot): a registration that commits between the per-key re-check and the
delete leaves metadata without an object. It needs a registration delayed past `min_age`, so
real runs require `min_age >= 24h`. It is detected, not prevented: every delete is followed by a
lookup, and a hit is reported in `deleted_but_registered` (the CLI logs ERROR
`evidence_object_deleted_while_registered` and exits non-zero) so the object can be restored from
a backup. The cure is a key-claim table shared by registration and cleanup (see the roadmap).
"""

import hashlib
import re
from collections.abc import Callable, Collection
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.review_core.application.evidence_storage import (
    EvidenceObjectInventory,
    EvidenceObjectStore,
    ListedObject,
    ListedUpload,
    ObjectNotFoundError,
    ObjectStoreError,
)
from easyaudit_next.review_core.domain.ids import EvidenceId
from easyaudit_next.review_core.domain.models import Evidence

LISTING_PREFIX = "org/"
_EVIDENCE_KEY = re.compile(r"^org/[^/]+/evidence/")
_BATCH = 500


class EvidenceReferences(Protocol):
    def referenced(self, storage_keys: Collection[str]) -> set[str]: ...

    def evidence_id_for_key(self, storage_key: str) -> str | None: ...

    def count(self) -> int: ...

    def alembic_revisions(self) -> set[str]: ...

    def page(
        self, organization_id: OrganizationId | None, after: EvidenceId | None, size: int
    ) -> list[Evidence]: ...


# Each `with` is a fresh, short transaction that sees everything committed so far.
ReferencesScope = Callable[[], AbstractContextManager[EvidenceReferences]]


class MaintenanceStore(EvidenceObjectStore, EvidenceObjectInventory, Protocol):
    pass


@dataclass(frozen=True, slots=True)
class DeletedWhileRegistered:
    storage_key: str
    evidence_id: str


@dataclass(slots=True)
class OrphanCleanupResult:
    scanned: int = 0
    orphans: int = 0  # unreferenced objects, young ones included
    deleted: int = 0
    kept_young: int = 0
    multipart_stale: int = 0
    multipart_aborted: int = 0
    skipped_referenced: int = 0  # unreferenced at the first check, referenced at the re-check
    failed: int = 0
    max_delete: int = 0
    deleted_but_registered: int = 0  # Evidence now has metadata but no object: restore it
    incidents: list[DeletedWhileRegistered] = field(default_factory=list)
    refused: str | None = None  # why nothing was deleted: see REFUSAL_* below


REFUSAL_NO_EVIDENCE_ROWS = "no_evidence_rows"
REFUSAL_REVISION_MISMATCH = "revision_mismatch"
REFUSAL_TOO_MANY_DELETIONS = "too_many_deletions"


async def cleanup_evidence_orphans(
    store: MaintenanceStore,
    references: ReferencesScope,
    *,
    min_age: timedelta,
    now: datetime,
    dry_run: bool,
    expected_revision: str,
    max_delete: int,
    result: OrphanCleanupResult | None = None,
    on_incident: Callable[[DeletedWhileRegistered], None] = lambda _incident: None,
) -> OrphanCleanupResult:
    """`result` may be supplied by the caller so that whatever was counted before an unexpected
    failure is still available to report. `on_incident` is called the moment a deleted object
    turns out to be registered, not at the end of the run."""
    result = result if result is not None else OrphanCleanupResult()
    result.max_delete = max_delete
    if not dry_run:
        with references() as checker:
            if checker.alembic_revisions() != {expected_revision}:
                result.refused = REFUSAL_REVISION_MISMATCH
                return result
    # Everything is listed before the first write: a listing that fails half-way must not leave
    # behind deletions or aborts that were decided on an incomplete picture.
    candidates: list[ListedObject] = []  # old orphans; never more than max_delete + 1 kept
    batch: list[ListedObject] = []
    old_orphans = 0
    async for item in store.list_objects(LISTING_PREFIX):
        if _EVIDENCE_KEY.match(item.key):
            batch.append(item)
            if len(batch) >= _BATCH:
                old_orphans += _classify(references, batch, result, candidates, min_age, now)
                batch = []
    old_orphans += _classify(references, batch, result, candidates, min_age, now)
    stale_uploads: list[ListedUpload] = []
    async for upload in store.list_multipart_uploads(LISTING_PREFIX):
        if _EVIDENCE_KEY.match(upload.key) and now - upload.initiated >= min_age:
            stale_uploads.append(upload)
    result.multipart_stale = len(stale_uploads)
    if dry_run:
        return result

    if result.scanned > 0:
        with references() as checker:
            if checker.count() == 0:
                result.refused = REFUSAL_NO_EVIDENCE_ROWS
                return result
    if old_orphans > max_delete:
        result.refused = REFUSAL_TOO_MANY_DELETIONS
        return result
    for item in candidates:
        with references() as checker:  # fresh transaction: a registration may have committed
            if checker.referenced([item.key]):
                result.skipped_referenced += 1
                continue
        delete_failed = False
        try:
            await store.delete(item.key)
        except ObjectStoreError:
            # The outcome of a failed delete is unknown: the object may be gone.
            result.failed += 1
            delete_failed = True
        else:
            result.deleted += 1
        await _detect_late_registration(
            store, references, item.key, delete_failed, result, on_incident
        )
    for upload in stale_uploads:
        try:
            await store.abort_multipart_upload(upload.key, upload.upload_id)
        except ObjectStoreError:
            result.failed += 1
        else:
            result.multipart_aborted += 1
    return result


async def _detect_late_registration(
    store: MaintenanceStore,
    references: ReferencesScope,
    key: str,
    delete_failed: bool,
    result: OrphanCleanupResult,
    on_incident: Callable[[DeletedWhileRegistered], None],
) -> None:
    """A registration that committed after the re-check leaves metadata without an object.
    After a delete that reported failure, only a registered key whose object is gone (or whose
    state cannot be read) counts."""
    with references() as checker:
        evidence_id = checker.evidence_id_for_key(key)
    if evidence_id is None:
        return
    if delete_failed:
        try:
            if await store.exists(key):
                return
        except ObjectStoreError:
            pass  # unknown: report it, the operator verifies
    incident = DeletedWhileRegistered(key, evidence_id)
    result.deleted_but_registered += 1
    result.incidents.append(incident)
    on_incident(incident)


def _classify(
    references: ReferencesScope,
    batch: list[ListedObject],
    result: OrphanCleanupResult,
    candidates: list[ListedObject],
    min_age: timedelta,
    now: datetime,
) -> int:
    """Count one batch; returns how many of it are old orphans (deletion candidates)."""
    if not batch:
        return 0
    result.scanned += len(batch)
    with references() as checker:
        referenced = checker.referenced([item.key for item in batch])
    old = 0
    for item in batch:
        if item.key in referenced:
            continue
        result.orphans += 1
        if now - item.last_modified < min_age:
            result.kept_young += 1
            continue
        old += 1
        if len(candidates) <= result.max_delete:
            candidates.append(item)
    return old


@dataclass(frozen=True, slots=True)
class EvidenceProblem:
    evidence_id: EvidenceId
    problem: str  # missing | size_mismatch | sha256_mismatch | read_error


@dataclass(slots=True)
class VerifyResult:
    checked: int = 0
    problems: list[EvidenceProblem] = field(default_factory=list)


async def verify_evidences(
    store: EvidenceObjectStore,
    references: ReferencesScope,
    *,
    organization_id: OrganizationId | None,
    limit: int | None,
) -> VerifyResult:
    """Read every object back and compare its size and streamed sha256 with the metadata.

    The database is read in short batches that end before any object is touched.
    """
    result = VerifyResult()
    after: EvidenceId | None = None
    while limit is None or result.checked < limit:
        size = _BATCH if limit is None else min(_BATCH, limit - result.checked)
        with references() as reader:
            page = reader.page(organization_id, after, size)
        if not page:
            break
        for evidence in page:
            result.checked += 1
            problem = await _check_one(store, evidence)
            if problem is not None:
                result.problems.append(EvidenceProblem(evidence.id, problem))
        after = page[-1].id
    return result


async def _check_one(store: EvidenceObjectStore, evidence: Evidence) -> str | None:
    try:
        stream = await store.open_stream(evidence.storage_key)
    except ObjectNotFoundError:
        return "missing"
    except ObjectStoreError:
        return "read_error"
    digest = hashlib.sha256()
    size = 0
    try:
        async for chunk in stream:
            digest.update(chunk)
            size += len(chunk)
    except ObjectStoreError:
        return "read_error"
    finally:
        await stream.aclose()
    if size != evidence.size_bytes:
        return "size_mismatch"
    if digest.hexdigest() != evidence.sha256:
        return "sha256_mismatch"
    return None
