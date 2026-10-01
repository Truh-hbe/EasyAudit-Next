"""S3 adapter for `EvidenceObjectStore` (Garage in production), on boto3/botocore.

Every call to the synchronous SDK runs in a worker thread so the event loop is never blocked.
Each socket operation is bounded by botocore's connect/read timeouts; those are per-operation
inactivity limits, not a total deadline, which is why readiness does not use this client.
Credentials are read from files, held only inside the botocore client, and never put in an
exception message, a log field or a readiness response; SDK exceptions are replaced by
`ObjectStoreError` (the original stays as `__cause__`, and the log formatter records exception
types only).
"""

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable
from functools import partial
from pathlib import Path
from typing import Any

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from easyaudit_next.infrastructure.observability import APP_LOGGER, describe_exception
from easyaudit_next.platform.settings import Settings
from easyaudit_next.review_core.application.evidence_storage import (
    ListedObject,
    ListedUpload,
    ObjectNotFoundError,
    ObjectStoreError,
    ObjectStoreNotConfiguredError,
    StoredObject,
)

DEFAULT_PART_SIZE = 8 * 1024 * 1024  # S3 requires >= 5 MiB for every part but the last
DOWNLOAD_CHUNK_SIZE = 64 * 1024  # what a download holds in memory at once
_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


def _read_secret(path: str) -> str:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ObjectStoreNotConfiguredError("Object storage credentials are unreadable") from exc
    if not value:
        raise ObjectStoreNotConfiguredError("Object storage credentials are empty")
    return value


def build_s3_client(
    settings: Settings,
    *,
    connect_timeout: float,
    read_timeout: float,
    total_attempts: int,
) -> BaseClient:
    """Blocking (reads the credential files). Call it off the event loop."""
    if not (
        settings.object_storage_endpoint
        and settings.object_storage_bucket
        and settings.object_storage_access_key_id_file
        and settings.object_storage_secret_access_key_file
    ):
        raise ObjectStoreNotConfiguredError("Object storage is not configured")
    return boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint,
        region_name=settings.object_storage_region,
        aws_access_key_id=_read_secret(settings.object_storage_access_key_id_file),
        aws_secret_access_key=_read_secret(settings.object_storage_secret_access_key_file),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            # `total_max_attempts` counts the first request; botocore's `max_attempts` counts only
            # the retries after it. Parts are in-memory bytes, so a retry is safe.
            retries={"total_max_attempts": total_attempts, "mode": "standard"},
            max_pool_connections=10,
            # The store is an internal endpoint: never route it through an ambient HTTP(S)_PROXY.
            proxies={},
            # Only checksum when the API demands it: S3-compatible servers differ in their
            # support for the SDK's default trailing checksums; we hash the stream ourselves.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


async def _call[T](function: Callable[[], T]) -> T:
    try:
        return await asyncio.to_thread(function)
    except (BotoCoreError, ClientError) as exc:
        raise ObjectStoreError("Object storage operation failed") from exc


def _close_abandoned_response(task: "asyncio.Future[Any]") -> None:
    """Done-callback for a GET whose caller was cancelled before it returned: close the Body
    the moment it exists. No bounded wait is needed, the close is tied to the GET finishing,
    which botocore's connect/read timeouts bound per socket operation."""
    if task.cancelled() or task.exception() is not None:
        return
    body = task.result().get("Body")
    if body is not None:
        # The close runs in the executor and handles its own errors: an exception left in a
        # discarded Future would be printed by asyncio's default handler, message and all.
        asyncio.get_running_loop().run_in_executor(None, _close_quietly, body)


def _close_quietly(body: Any) -> None:
    try:
        body.close()
    except Exception as exc:
        APP_LOGGER.warning(
            "object_stream_close_failed", extra={"exception_details": describe_exception(exc)}
        )


class _S3ObjectStream:
    """Reads one `GetObject` body in small chunks, each in a worker thread.

    Cancelling `__anext__` abandons a thread that is blocked in `read`; it ends on its own
    (botocore's `read_timeout` bounds it) and its result is dropped. `aclose` closes the body
    and cannot be interrupted half-way: the close runs in a shielded thread call.
    """

    def __init__(self, body: Any, chunk_size: int, content_length: int | None) -> None:
        self.content_length = content_length
        self._body = body
        self._chunk_size = chunk_size
        self._closed = False

    def __aiter__(self) -> "_S3ObjectStream":
        return self

    async def __anext__(self) -> bytes:
        if self._closed:
            raise StopAsyncIteration
        try:
            chunk: bytes = await _call(lambda: self._body.read(self._chunk_size))
        except BaseException:
            await self.aclose()
            raise
        if not chunk:
            await self.aclose()
            raise StopAsyncIteration
        return chunk

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await asyncio.shield(asyncio.to_thread(self._body.close))
        except Exception:
            pass  # nothing useful to do: the connection is dropped either way


class S3EvidenceObjectStore:
    def __init__(
        self, client: BaseClient, bucket: str, *, part_size: int = DEFAULT_PART_SIZE
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._part_size = part_size

    @classmethod
    def from_settings(cls, settings: Settings) -> "S3EvidenceObjectStore":
        client = build_s3_client(
            settings,
            connect_timeout=settings.object_storage_connect_timeout_seconds,
            read_timeout=settings.object_storage_read_timeout_seconds,
            total_attempts=settings.object_storage_max_attempts,
        )
        return cls(client, settings.object_storage_bucket)

    async def put_stream(self, key: str, chunks: AsyncIterator[bytes]) -> StoredObject:
        digest = hashlib.sha256()
        size = 0
        buffer = bytearray()  # at most one part plus one incoming chunk
        upload_id: str | None = None
        parts: list[dict[str, Any]] = []
        try:
            async for chunk in chunks:
                digest.update(chunk)
                size += len(chunk)
                buffer.extend(chunk)
                while len(buffer) >= self._part_size:
                    body = bytes(buffer[: self._part_size])
                    del buffer[: self._part_size]
                    if upload_id is None:
                        upload_id = await self._create_multipart(key)
                    parts.append(await self._upload_part(key, upload_id, len(parts) + 1, body))
            if upload_id is None:
                body = bytes(buffer)
                await _call(
                    lambda: self._client.put_object(Bucket=self._bucket, Key=key, Body=body)
                )
            else:
                if buffer:
                    parts.append(
                        await self._upload_part(key, upload_id, len(parts) + 1, bytes(buffer))
                    )
                await _call(
                    lambda: self._client.complete_multipart_upload(
                        Bucket=self._bucket,
                        Key=key,
                        UploadId=upload_id,
                        MultipartUpload={"Parts": parts},
                    )
                )
        except BaseException:
            if upload_id is not None:
                await self._abort_quietly(key, upload_id)
            raise
        return StoredObject(size, digest.hexdigest())

    async def delete(self, key: str) -> None:
        await _call(lambda: self._client.delete_object(Bucket=self._bucket, Key=key))

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(lambda: self._client.head_object(Bucket=self._bucket, Key=key))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _NOT_FOUND_CODES:
                return False
            raise ObjectStoreError("Object storage operation failed") from exc
        except BotoCoreError as exc:
            raise ObjectStoreError("Object storage operation failed") from exc
        return True

    async def open_stream(self, key: str) -> _S3ObjectStream:
        task = asyncio.ensure_future(
            asyncio.to_thread(lambda: self._client.get_object(Bucket=self._bucket, Key=key))
        )
        try:
            # Shielded: a cancelled request cannot stop the worker thread, and whatever the GET
            # returns afterwards owns a connection that someone has to close.
            response = await asyncio.shield(task)
        except asyncio.CancelledError:
            task.add_done_callback(_close_abandoned_response)
            raise
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _NOT_FOUND_CODES:
                raise ObjectNotFoundError("Object not found") from exc
            raise ObjectStoreError("Object storage operation failed") from exc
        except BotoCoreError as exc:
            raise ObjectStoreError("Object storage operation failed") from exc
        length = response.get("ContentLength")
        return _S3ObjectStream(
            response["Body"], DOWNLOAD_CHUNK_SIZE, int(length) if length is not None else None
        )

    async def list_objects(self, prefix: str) -> AsyncIterator[ListedObject]:
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix}
            if token is not None:
                kwargs["ContinuationToken"] = token
            page = await _call(partial(self._client.list_objects_v2, **kwargs))
            for item in page.get("Contents", []):
                yield ListedObject(item["Key"], item["LastModified"], int(item["Size"]))
            if not page.get("IsTruncated"):
                return
            token = page["NextContinuationToken"]

    async def list_multipart_uploads(self, prefix: str) -> AsyncIterator[ListedUpload]:
        key_marker: str | None = None
        upload_marker: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix}
            if key_marker is not None:
                kwargs["KeyMarker"] = key_marker
            if upload_marker is not None:
                kwargs["UploadIdMarker"] = upload_marker
            page = await _call(partial(self._client.list_multipart_uploads, **kwargs))
            for item in page.get("Uploads", []):
                yield ListedUpload(item["Key"], item["UploadId"], item["Initiated"])
            if not page.get("IsTruncated"):
                return
            key_marker = page.get("NextKeyMarker")
            upload_marker = page.get("NextUploadIdMarker")

    async def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        await _call(
            lambda: self._client.abort_multipart_upload(
                Bucket=self._bucket, Key=key, UploadId=upload_id
            )
        )

    async def _create_multipart(self, key: str) -> str:
        response = await _call(
            lambda: self._client.create_multipart_upload(Bucket=self._bucket, Key=key)
        )
        return str(response["UploadId"])

    async def _upload_part(
        self, key: str, upload_id: str, number: int, body: bytes
    ) -> dict[str, Any]:
        response = await _call(
            lambda: self._client.upload_part(
                Bucket=self._bucket, Key=key, UploadId=upload_id, PartNumber=number, Body=body
            )
        )
        return {"ETag": response["ETag"], "PartNumber": number}

    async def _abort_quietly(self, key: str, upload_id: str) -> None:
        """Runs while an exception (possibly a cancellation) is propagating; must not replace it."""
        try:
            await asyncio.shield(
                _call(
                    lambda: self._client.abort_multipart_upload(
                        Bucket=self._bucket, Key=key, UploadId=upload_id
                    )
                )
            )
        except Exception:
            pass  # the original failure is what the caller must see; the upload is orphaned
