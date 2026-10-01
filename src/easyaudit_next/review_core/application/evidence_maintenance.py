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

    def page(
        self, organization_id: OrganizationId | None, after: EvidenceId | None, size: int
    ) -> list[Evidence]: ...


# Each `with` is a fresh, short transaction that sees everything committed so far.
ReferencesScope = Callable[[], AbstractContextManager[EvidenceReferences]]


class MaintenanceStore(EvidenceObjectStore, EvidenceObjectInventory, Protocol):
    pass


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


async def cleanup_evidence_orphans(
    store: MaintenanceStore,
    references: ReferencesScope,
    *,
    min_age: timedelta,
    now: datetime,
    dry_run: bool,
) -> OrphanCleanupResult:
    result = OrphanCleanupResult()
    batch: list[ListedObject] = []
    async for item in store.list_objects(LISTING_PREFIX):
        if _EVIDENCE_KEY.match(item.key):
            batch.append(item)
            if len(batch) >= _BATCH:
                await _process_batch(store, references, batch, result, min_age, now, dry_run)
                batch = []
    await _process_batch(store, references, batch, result, min_age, now, dry_run)

    async for upload in store.list_multipart_uploads(LISTING_PREFIX):
        if not _EVIDENCE_KEY.match(upload.key) or now - upload.initiated < min_age:
            continue
        result.multipart_stale += 1
        if dry_run:
            continue
        try:
            await store.abort_multipart_upload(upload.key, upload.upload_id)
        except ObjectStoreError:
            result.failed += 1
        else:
            result.multipart_aborted += 1
    return result


async def _process_batch(
    store: MaintenanceStore,
    references: ReferencesScope,
    batch: list[ListedObject],
    result: OrphanCleanupResult,
    min_age: timedelta,
    now: datetime,
    dry_run: bool,
) -> None:
    if not batch:
        return
    result.scanned += len(batch)
    with references() as checker:
        referenced = checker.referenced([item.key for item in batch])
    for item in batch:
        if item.key in referenced:
            continue
        result.orphans += 1
        if now - item.last_modified < min_age:
            result.kept_young += 1
            continue
        if dry_run:
            continue
        with references() as checker:  # fresh transaction: a registration may have committed
            if checker.referenced([item.key]):
                result.skipped_referenced += 1
                continue
        try:
            await store.delete(item.key)
        except ObjectStoreError:
            result.failed += 1
        else:
            result.deleted += 1


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
