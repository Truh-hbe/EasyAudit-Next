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
