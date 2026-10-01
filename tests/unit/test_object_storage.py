"""S3 adapter against a real in-process S3 server (moto), plus the readiness probe."""

import asyncio
import hashlib
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest

from easyaudit_next.infrastructure import readiness
from easyaudit_next.infrastructure.object_storage import S3EvidenceObjectStore
from easyaudit_next.platform.settings import Settings
from easyaudit_next.review_core.application.evidence_storage import (
    EvidenceTooLargeError,
    ObjectStoreError,
    limit_stream,
)
from tests.conftest import SECRET_KEY, FakeS3, SilentTcpServer

MIB = 1024 * 1024
PART = 5 * MIB  # the smallest part size S3 (and moto) accepts


def make_store(fake: FakeS3, part_size: int = PART) -> S3EvidenceObjectStore:
    base = S3EvidenceObjectStore.from_settings(fake.settings())
    return S3EvidenceObjectStore(base._client, fake.bucket, part_size=part_size)


async def chunked(data: bytes, size: int = 64 * 1024) -> AsyncIterator[bytes]:
    for offset in range(0, len(data), size):
        yield data[offset : offset + size]
        await asyncio.sleep(0)


def read_back(fake: FakeS3, key: str) -> bytes:
    body: bytes = fake.client().get_object(Bucket=fake.bucket, Key=key)["Body"].read()
    return body


def test_small_object_is_written_with_a_single_put(fake_s3: FakeS3) -> None:
    data = b"small evidence\n" * 100
    store = make_store(fake_s3)

    stored = asyncio.run(store.put_stream("org/o/evidence/one", chunked(data)))

    assert stored.size_bytes == len(data)
    assert stored.sha256 == hashlib.sha256(data).hexdigest()
    assert read_back(fake_s3, "org/o/evidence/one") == data


def test_large_object_is_uploaded_in_bounded_parts(fake_s3: FakeS3) -> None:
    data = bytes(range(256)) * (11 * MIB // 256) + b"tail"
    store = make_store(fake_s3)
    sizes: list[int] = []
    original = store._client.upload_part

    def spy(**kwargs: Any) -> Any:
        sizes.append(len(kwargs["Body"]))
        return original(**kwargs)

    store._client.upload_part = spy  # type: ignore[method-assign]

    stored = asyncio.run(store.put_stream("org/o/evidence/big", chunked(data)))

    assert sizes == [PART, PART, len(data) - 2 * PART]
    assert max(sizes) <= PART
    assert stored.size_bytes == len(data)
    assert stored.sha256 == hashlib.sha256(data).hexdigest()
    assert read_back(fake_s3, "org/o/evidence/big") == data
    assert fake_s3.open_uploads() == []


def test_failing_source_after_parts_were_written_aborts_the_multipart_upload(
    fake_s3: FakeS3,
) -> None:
    class SourceFailed(Exception):
        pass

    async def failing() -> AsyncIterator[bytes]:
        yield b"x" * (PART + 10)
        raise SourceFailed

    with pytest.raises(SourceFailed):
        asyncio.run(make_store(fake_s3).put_stream("org/o/evidence/broken", failing()))

    assert fake_s3.keys() == []
    assert fake_s3.open_uploads() == []


def test_size_limit_hit_mid_stream_leaves_no_object_and_no_open_upload(
    fake_s3: FakeS3,
) -> None:
    data = b"z" * (2 * PART + 1)
    limited = limit_stream(chunked(data), 2 * PART)

    with pytest.raises(EvidenceTooLargeError):
        asyncio.run(make_store(fake_s3).put_stream("org/o/evidence/huge", limited))

    assert fake_s3.keys() == []
    assert fake_s3.open_uploads() == []


def test_exists_and_delete(fake_s3: FakeS3) -> None:
    store = make_store(fake_s3)

    async def scenario() -> tuple[bool, bool, bool]:
        before = await store.exists("org/o/evidence/k")
        await store.put_stream("org/o/evidence/k", chunked(b"abc"))
        present = await store.exists("org/o/evidence/k")
        await store.delete("org/o/evidence/k")
        await store.delete("org/o/evidence/k")  # idempotent
        return before, present, await store.exists("org/o/evidence/k")

    assert asyncio.run(scenario()) == (False, True, False)


def test_store_failures_become_opaque_object_store_errors(fake_s3: FakeS3) -> None:
    base = S3EvidenceObjectStore.from_settings(fake_s3.settings())
    store = S3EvidenceObjectStore(base._client, "no-such-bucket")

    with pytest.raises(ObjectStoreError) as caught:
        asyncio.run(store.put_stream("k", chunked(b"abc")))

    assert fake_s3.access_key not in str(caught.value)
    assert SECRET_KEY not in str(caught.value)
    assert "no-such-bucket" not in str(caught.value)


# --- readiness probe ---------------------------------------------------------------------


def probe(settings: Settings) -> Any:
    return asyncio.run(readiness.fetch_object_storage_failure(settings))


def test_probe_is_ok_when_the_bucket_answers(fake_s3: FakeS3) -> None:
    assert probe(fake_s3.settings()) is None


def test_probe_fails_without_detail_for_a_missing_bucket(fake_s3: FakeS3) -> None:
    failure = probe(fake_s3.settings(object_storage_bucket="missing-bucket"))

    assert failure is not None and failure.reason == "unreachable"
    assert SECRET_KEY not in repr(failure) and "missing-bucket" not in repr(failure)


def test_probe_fails_when_unconfigured() -> None:
    failure = probe(Settings())

    assert failure is not None and failure.reason == "not_configured"


def test_probe_fails_when_the_endpoint_refuses_connections(fake_s3: FakeS3) -> None:
    started = time.monotonic()
    failure = probe(fake_s3.settings(object_storage_endpoint="http://127.0.0.1:1"))

    assert failure is not None and failure.reason == "unreachable"
    assert time.monotonic() - started < 2


def test_probe_returns_within_the_deadline_against_a_silent_server(
    fake_s3: FakeS3, silent_server: SilentTcpServer
) -> None:
    settings = fake_s3.settings(
        object_storage_endpoint=silent_server.endpoint, readiness_timeout_seconds=1
    )

    async def timed() -> tuple[Any, float]:
        started = time.monotonic()
        failure = await readiness.fetch_object_storage_failure(settings)
        return failure, time.monotonic() - started

    failure, elapsed = asyncio.run(timed())  # elapsed is measured inside the event loop

    assert failure is not None and failure.reason == "deadline_exceeded"
    assert elapsed < 1.5


def test_abandoned_probe_thread_ends_on_its_own_so_shutdown_is_bounded(
    fake_s3: FakeS3, silent_server: SilentTcpServer
) -> None:
    """`asyncio.run` waits for the default executor on exit, like uvicorn's shutdown does: if the
    probe thread outlived its socket timeouts this would hang far longer than the deadline."""
    settings = fake_s3.settings(
        object_storage_endpoint=silent_server.endpoint, readiness_timeout_seconds=1
    )
    started = time.monotonic()

    probe(settings)

    assert time.monotonic() - started < 3.5
