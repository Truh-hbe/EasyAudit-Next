import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable

from easyaudit_next.review_core.application.evidence_storage import (
    ObjectNotFoundError,
    StoredObject,
)


class FakeObjectStream:
    def __init__(
        self, data: bytes, chunk_size: int, between_chunks: Callable[[], None] | None
    ) -> None:
        self._data = data
        self.content_length: int | None = len(data)
        self._chunk_size = chunk_size
        self._between_chunks = between_chunks
        self._offset = 0
        self.closed = False
        self.chunks_served = 0

    def __aiter__(self) -> "FakeObjectStream":
        return self

    async def __anext__(self) -> bytes:
        await asyncio.sleep(0)  # a real read yields to the loop
        if self.closed or self._offset >= len(self._data):
            raise StopAsyncIteration
        if self._between_chunks is not None:
            self._between_chunks()
        chunk = self._data[self._offset : self._offset + self._chunk_size]
        self._offset += len(chunk)
        self.chunks_served += 1
        return chunk

    async def aclose(self) -> None:
        self.closed = True


class FakeEvidenceStore:
    """In-memory EvidenceObjectStore honouring the port contract: an object appears under its
    key only once the whole stream was consumed; a failing stream leaves nothing behind."""

    def __init__(
        self,
        *,
        while_receiving: Callable[[], None] | None = None,
        after_received: Callable[[], None] | None = None,
        fail_delete: bool = False,
        download_chunk_size: int = 4,
        while_streaming: Callable[[], None] | None = None,
    ) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[str] = []
        self.deleted: list[str] = []
        self.while_receiving = while_receiving
        self.after_received = after_received
        self.fail_delete = fail_delete
        self.download_chunk_size = download_chunk_size
        self.while_streaming = while_streaming
        self.open_calls: list[str] = []
        self.streams: list[FakeObjectStream] = []

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

    async def open_stream(self, key: str) -> FakeObjectStream:
        self.open_calls.append(key)
        if key not in self.objects:
            raise ObjectNotFoundError("Object not found")
        stream = FakeObjectStream(self.objects[key], self.download_chunk_size, self.while_streaming)
        self.streams.append(stream)
        return stream
