"""Port for Evidence file bytes. Adapters live in `infrastructure/`; nothing here knows S3."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from easyaudit_next.platform.domain.ids import OrganizationId


class ObjectStoreError(Exception):
    """The object store failed. The message never carries endpoint, bucket or credentials."""


class EvidenceTooLargeError(Exception):
    def __init__(self, max_bytes: int) -> None:
        super().__init__("Evidence exceeds the maximum size")
        self.max_bytes = max_bytes


@dataclass(frozen=True, slots=True)
class StoredObject:
    size_bytes: int
    sha256: str


class ObjectNotFoundError(ObjectStoreError):
    """The store answered, and there is no object under that key."""


class ObjectStream(Protocol):
    """Chunks of one object. `aclose` releases the underlying connection and is safe to call
    at any point, more than once, whether or not iteration started."""

    content_length: int | None
    """What the store says the object's size is, known before the first chunk."""

    def __aiter__(self) -> "ObjectStream": ...

    async def __anext__(self) -> bytes: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ListedObject:
    key: str
    last_modified: datetime
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ListedUpload:
    key: str
    upload_id: str
    initiated: datetime


class EvidenceObjectStore(Protocol):
    async def put_stream(self, key: str, chunks: AsyncIterator[bytes]) -> StoredObject:
        """Write `chunks` under a new `key`, hashing and counting them on the way.

        Memory is bounded by one part, never by the object size. If `chunks` or the store
        fails, nothing is left under `key` (incomplete multipart uploads are aborted) and
        the original exception propagates; store failures surface as `ObjectStoreError`.
        """
        ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    async def open_stream(self, key: str) -> ObjectStream:
        """Start reading `key`. Raises `ObjectNotFoundError` when it is absent and
        `ObjectStoreError` on any other store failure, both *before* the first chunk, so a
        caller can still choose its response. Chunks are small and bounded; memory does not
        depend on the object size. The caller must `aclose()` the stream."""
        ...


class EvidenceObjectInventory(Protocol):
    """What the maintenance commands need beyond reading and writing single objects."""

    def list_objects(self, prefix: str) -> AsyncIterator[ListedObject]: ...

    def list_multipart_uploads(self, prefix: str) -> AsyncIterator[ListedUpload]: ...

    async def abort_multipart_upload(self, key: str, upload_id: str) -> None: ...


def new_storage_key(organization_id: OrganizationId) -> str:
    """Server-generated and written once. The client's file name never takes part in it."""
    return f"org/{organization_id}/evidence/{uuid4()}"


async def limit_stream(chunks: AsyncIterator[bytes], max_bytes: int) -> AsyncIterator[bytes]:
    """Abort as soon as the running total passes `max_bytes`, before the offending chunk is
    handed on."""
    total = 0
    async for chunk in chunks:
        total += len(chunk)
        if total > max_bytes:
            raise EvidenceTooLargeError(max_bytes)
        yield chunk


class ObjectStoreNotConfiguredError(ObjectStoreError):
    pass
