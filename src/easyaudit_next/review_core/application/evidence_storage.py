"""Port for Evidence file bytes. Adapters live in `infrastructure/`; nothing here knows S3."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
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
