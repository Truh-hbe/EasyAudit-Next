"""S3 adapter against a real in-process S3 server (moto), plus the readiness probe."""

import asyncio
import hashlib
import threading
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest

from easyaudit_next.infrastructure import readiness
from easyaudit_next.infrastructure.object_storage import S3EvidenceObjectStore
from easyaudit_next.platform.settings import Settings
from easyaudit_next.review_core.application.evidence_storage import (
    EvidenceTooLargeError,
    ObjectNotFoundError,
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


# --- readiness probe (reachability only, no threads) -------------------------------------


def probe(settings: Settings) -> Any:
    return asyncio.run(readiness.fetch_object_storage_failure(settings))


def test_probe_is_ok_when_the_endpoint_answers_http(fake_s3: FakeS3) -> None:
    assert probe(fake_s3.settings()) is None


def test_any_http_status_counts_as_reachable_even_for_a_missing_bucket(fake_s3: FakeS3) -> None:
    """Reachability only: credentials and the bucket are not validated by readiness."""
    assert probe(fake_s3.settings(object_storage_bucket="missing-bucket")) is None


def test_probe_fails_when_unconfigured() -> None:
    failure = probe(Settings())

    assert failure is not None and failure.reason == "not_configured"


def test_probe_fails_when_the_endpoint_refuses_connections(fake_s3: FakeS3) -> None:
    failure = probe(fake_s3.settings(object_storage_endpoint="http://127.0.0.1:1"))

    assert failure is not None and failure.reason == "unreachable"


def test_probe_fails_when_the_peer_does_not_speak_http(fake_s3: FakeS3) -> None:
    import socket
    import threading

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def garbage() -> None:
        connection, _ = server.accept()
        connection.sendall(b"SSH-2.0-OpenSSH\r\n")
        connection.close()

    threading.Thread(target=garbage, daemon=True).start()
    endpoint = f"http://127.0.0.1:{server.getsockname()[1]}"

    failure = probe(fake_s3.settings(object_storage_endpoint=endpoint))
    server.close()

    assert failure is not None and failure.reason == "unreachable"


def test_probe_and_loop_exit_are_bounded_against_hostile_servers(
    fake_s3: FakeS3, hostile_server: SilentTcpServer
) -> None:
    """Silent, slow-dripping and resetting peers: the answer and the whole `asyncio.run`
    (which also waits for the default executor, like uvicorn's shutdown) stay within the
    deadline plus a little."""
    settings = fake_s3.settings(
        object_storage_endpoint=hostile_server.endpoint, readiness_timeout_seconds=1
    )
    started = time.monotonic()

    failure = probe(settings)

    elapsed = time.monotonic() - started  # includes loop shutdown
    assert failure is not None and failure.reason in {"deadline_exceeded", "unreachable"}
    assert elapsed < 1.6


def test_client_retry_budget_counts_the_first_attempt(fake_s3: FakeS3) -> None:
    store = S3EvidenceObjectStore.from_settings(fake_s3.settings(object_storage_max_attempts=2))

    retries = store._client.meta.config.retries

    assert retries["total_max_attempts"] == 2 and retries["mode"] == "standard"
    assert store._client.meta.config.proxies == {}


def test_a_stuck_resolver_cannot_delay_the_probe_or_the_loop_exit(
    fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`getaddrinfo` cannot be interrupted. It runs in the probe's own daemon thread, not on the
    default executor, so neither the answer nor `asyncio.run`'s exit waits for it."""
    monkeypatch.setattr(readiness.socket, "getaddrinfo", lambda *a, **k: time.sleep(2.5) or [])
    settings = fake_s3.settings(
        object_storage_endpoint="http://storage.internal.test:3900", readiness_timeout_seconds=1
    )
    started = time.monotonic()

    failure = probe(settings)

    assert failure is not None and failure.reason == "deadline_exceeded"
    assert time.monotonic() - started < 1.6  # includes the loop's shutdown


def test_a_hostname_is_resolved_then_reached_by_address(
    fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket as socket_module

    port = fake_s3.endpoint.rsplit(":", 1)[1]
    seen: list[str] = []

    def fake_getaddrinfo(host: str, p: int, **_: Any) -> list[Any]:
        seen.append(host)
        return [(socket_module.AF_INET, socket_module.SOCK_STREAM, 6, "", ("127.0.0.1", p))]

    monkeypatch.setattr(readiness.socket, "getaddrinfo", fake_getaddrinfo)

    failure = probe(fake_s3.settings(object_storage_endpoint=f"http://storage.test:{port}"))

    assert failure is None and seen == ["storage.test"]


def test_head_request_formats_host_and_bucket_like_the_endpoint(fake_s3: FakeS3) -> None:
    request = readiness._head_request(
        fake_s3.settings(object_storage_endpoint="http://[::1]:3900/", object_storage_bucket="a b")
    )
    assert request.startswith(b"HEAD /a%20b HTTP/1.1\r\nHost: [::1]:3900\r\n")
    plain = readiness._head_request(
        fake_s3.settings(object_storage_endpoint="https://s3.example.com")
    )
    assert b"Host: s3.example.com\r\n" in plain


def test_probe_reaches_an_ipv6_literal_endpoint(fake_s3: FakeS3) -> None:
    import socket

    try:
        server = socket.socket(socket.AF_INET6)
        server.bind(("::1", 0))
    except OSError:
        pytest.skip("no IPv6 loopback")
    server.listen(1)
    port = server.getsockname()[1]

    def answer() -> None:
        connection, _ = server.accept()
        connection.recv(1024)
        connection.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        connection.close()

    import threading

    threading.Thread(target=answer, daemon=True).start()

    failure = probe(fake_s3.settings(object_storage_endpoint=f"http://[::1]:{port}"))
    server.close()

    assert failure is None


def test_open_stream_reads_in_bounded_chunks_and_closes_the_body_at_the_end(
    fake_s3: FakeS3,
) -> None:
    data = bytes(range(256)) * 1000
    fake_s3.client().put_object(Bucket=fake_s3.bucket, Key="org/o/evidence/d", Body=data)
    store = make_store(fake_s3)

    async def scenario() -> tuple[bytes, list[int], Any]:
        stream = await store.open_stream("org/o/evidence/d")
        body = stream._body
        closed: list[bool] = []
        original_close = body.close
        body.close = lambda: (closed.append(True), original_close())[1]
        sizes: list[int] = []
        received = bytearray()
        async for chunk in stream:
            sizes.append(len(chunk))
            received.extend(chunk)
        return bytes(received), sizes, closed

    received, sizes, closed = asyncio.run(scenario())

    assert received == data
    assert max(sizes) <= 64 * 1024 and len(sizes) > 3
    assert closed == [True]


def test_open_stream_of_an_absent_key_raises_not_found_before_any_chunk(fake_s3: FakeS3) -> None:
    store = make_store(fake_s3)

    with pytest.raises(ObjectNotFoundError):
        asyncio.run(store.open_stream("org/o/evidence/absent"))


def test_closing_a_stream_early_or_cancelling_a_read_closes_the_body(fake_s3: FakeS3) -> None:
    fake_s3.client().put_object(
        Bucket=fake_s3.bucket, Key="org/o/evidence/e", Body=b"x" * (300 * 1024)
    )
    store = make_store(fake_s3)

    async def early_close() -> bool:
        stream = await store.open_stream("org/o/evidence/e")
        closed = False
        original = stream._body.close

        def close() -> None:
            nonlocal closed
            closed = True
            original()

        stream._body.close = close
        await anext(stream)
        await stream.aclose()
        await stream.aclose()  # idempotent
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        return closed

    async def cancelled_read() -> bool:
        stream = await store.open_stream("org/o/evidence/e")
        in_read, release = threading.Event(), threading.Event()
        original = stream._body.read

        def blocked_read(amount: int) -> bytes:
            in_read.set()
            release.wait(5)
            return original(amount)

        stream._body.read = blocked_read
        task = asyncio.ensure_future(anext(stream))
        await asyncio.to_thread(in_read.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        return stream._closed

    assert asyncio.run(early_close()) is True
    assert asyncio.run(cancelled_read()) is True


def test_listing_objects_and_multipart_uploads_pages_through_everything(
    fake_s3: FakeS3,
) -> None:
    client = fake_s3.client()
    for index in range(7):
        client.put_object(Bucket=fake_s3.bucket, Key=f"org/o/evidence/{index}", Body=b"x")
    uploads = [
        client.create_multipart_upload(Bucket=fake_s3.bucket, Key=f"org/o/evidence/mp{index}")[
            "UploadId"
        ]
        for index in range(3)
    ]
    store = make_store(fake_s3)
    inventory: Any = store
    original = store._client.list_objects_v2
    pages: list[int] = []

    def small_pages(**kwargs: Any) -> Any:
        pages.append(1)
        return original(**{**kwargs, "MaxKeys": 3})

    store._client.list_objects_v2 = small_pages  # type: ignore[method-assign]

    async def scenario() -> tuple[list[str], list[str]]:
        objects = [item.key async for item in inventory.list_objects("org/")]
        listed = [item async for item in inventory.list_multipart_uploads("org/")]
        for item in listed:
            await inventory.abort_multipart_upload(item.key, item.upload_id)
        return objects, [item.upload_id for item in listed]

    objects, found = asyncio.run(scenario())

    assert sorted(objects) == sorted(f"org/o/evidence/{i}" for i in range(7))
    assert len(pages) == 3
    assert sorted(found) == sorted(uploads)
    assert fake_s3.open_uploads() == []


def test_a_get_cancelled_before_it_returns_still_closes_the_body_it_gets_later() -> None:
    from unittest.mock import MagicMock

    release, in_get = threading.Event(), threading.Event()
    body = MagicMock()

    class SlowClient:
        def get_object(self, **_: Any) -> dict[str, Any]:
            in_get.set()
            release.wait(5)
            return {"Body": body, "ContentLength": 3}

    store = S3EvidenceObjectStore(SlowClient(), "bucket")  # type: ignore[arg-type]

    async def scenario() -> None:
        task = asyncio.ensure_future(store.open_stream("org/o/evidence/k"))
        await asyncio.to_thread(in_get.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        body.close.assert_not_called()  # still in flight: nothing to close yet
        release.set()
        for _ in range(100):
            if body.close.called:
                break
            await asyncio.sleep(0.01)

    asyncio.run(scenario())

    body.close.assert_called_once()


def test_a_close_that_raises_after_cancellation_is_logged_by_type_and_never_reaches_asyncio(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from unittest.mock import MagicMock

    release, in_get = threading.Event(), threading.Event()
    body = MagicMock()
    body.close.side_effect = RuntimeError("secret-endpoint.internal rejected the close")
    unretrieved: list[dict[str, Any]] = []

    class SlowClient:
        def get_object(self, **_: Any) -> dict[str, Any]:
            in_get.set()
            release.wait(5)
            return {"Body": body, "ContentLength": 3}

    store = S3EvidenceObjectStore(SlowClient(), "bucket")  # type: ignore[arg-type]

    async def scenario() -> None:
        asyncio.get_running_loop().set_exception_handler(lambda _l, ctx: unretrieved.append(ctx))
        task = asyncio.ensure_future(store.open_stream("org/o/evidence/k"))
        await asyncio.to_thread(in_get.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        for _ in range(100):
            if body.close.called:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.1)
        import gc

        gc.collect()

    with caplog.at_level("WARNING", logger="easyaudit.app"):
        asyncio.run(scenario())

    assert unretrieved == []
    [record] = [r for r in caplog.records if r.getMessage() == "object_stream_close_failed"]
    assert "secret-endpoint" not in record.getMessage()
    assert "secret-endpoint" not in str(getattr(record, "exception_details", ""))
