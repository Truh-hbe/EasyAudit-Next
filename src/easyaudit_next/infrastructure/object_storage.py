"""S3 adapter for `EvidenceObjectStore` (Garage in production), on boto3/botocore.

Every call to the synchronous SDK runs in a worker thread so the event loop is never blocked,
and every call is bounded by botocore's socket-level connect/read timeouts. Credentials are
read from files, held only inside the botocore client, and never put in an exception message,
a log field or a readiness response; SDK exceptions are replaced by `ObjectStoreError` (the
original stays as `__cause__`, and the log formatter records exception types only).
"""

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from easyaudit_next.platform.settings import Settings
from easyaudit_next.review_core.application.evidence_storage import (
    ObjectStoreError,
    ObjectStoreNotConfiguredError,
    StoredObject,
)

DEFAULT_PART_SIZE = 8 * 1024 * 1024  # S3 requires >= 5 MiB for every part but the last


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
    max_attempts: int,
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
            retries={"max_attempts": max_attempts, "mode": "standard"},
            max_pool_connections=10,
            # The store is an internal endpoint: never route it through an ambient HTTP(S)_PROXY.
            proxies={},
            # Only checksum when the API demands it: S3-compatible servers differ in their
            # support for the SDK's default trailing checksums; we hash the stream ourselves.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def head_bucket(settings: Settings) -> None:
    """Readiness probe body: one HeadBucket with a single attempt and socket timeouts equal
    to the readiness deadline, so the worker thread ends by itself even if nobody awaits it."""
    client = build_s3_client(
        settings,
        connect_timeout=settings.readiness_timeout_seconds,
        read_timeout=settings.readiness_timeout_seconds,
        max_attempts=1,
    )
    try:
        client.head_bucket(Bucket=settings.object_storage_bucket)
    finally:
        client.close()


async def _call[T](function: Callable[[], T]) -> T:
    try:
        return await asyncio.to_thread(function)
    except (BotoCoreError, ClientError) as exc:
        raise ObjectStoreError("Object storage operation failed") from exc


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
            max_attempts=settings.object_storage_max_attempts,
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
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise ObjectStoreError("Object storage operation failed") from exc
        except BotoCoreError as exc:
            raise ObjectStoreError("Object storage operation failed") from exc
        return True

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
