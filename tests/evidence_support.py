import hashlib
from collections.abc import AsyncIterator, Callable

from easyaudit_next.review_core.application.evidence_storage import StoredObject


class FakeEvidenceStore:
    """In-memory EvidenceObjectStore honouring the port contract: an object appears under its
    key only once the whole stream was consumed; a failing stream leaves nothing behind."""

    def __init__(
        self,
        *,
        while_receiving: Callable[[], None] | None = None,
        after_received: Callable[[], None] | None = None,
        fail_delete: bool = False,
    ) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[str] = []
        self.deleted: list[str] = []
        self.while_receiving = while_receiving
        self.after_received = after_received
        self.fail_delete = fail_delete

    async def put_stream(self, key: str, chunks: AsyncIterator[bytes]) -> StoredObject:
        self.put_calls.append(key)
        if self.while_receiving is not None:
            self.while_receiving()  # before the first byte is read
        received = bytearray()
        digest = hashlib.sha256()
        async for chunk in chunks:
            received.extend(chunk)
            digest.update(chunk)
        if self.after_received is not None:
            self.after_received()  # the body is in, nothing is stored yet
        assert key not in self.objects, "keys are written once"
        self.objects[key] = bytes(received)
        return StoredObject(len(received), digest.hexdigest())

    async def delete(self, key: str) -> None:
        if self.fail_delete:
            raise RuntimeError("delete failed")
        self.deleted.append(key)
        self.objects.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.objects
