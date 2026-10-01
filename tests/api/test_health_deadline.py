"""Readiness must return by its own deadline even when the database never answers."""

import asyncio
import struct
import threading
import time
from collections.abc import Awaitable, Callable
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easyaudit_next.api import health
from easyaudit_next.infrastructure import readiness
from easyaudit_next.infrastructure.readiness import DatabaseState
from easyaudit_next.main import create_app
from easyaudit_next.platform.settings import Settings

TIMEOUT = 0.5
MARGIN = 1.0

Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


class BlackHole:
    """TCP server that never speaks PostgreSQL. Records connections and client hang-ups."""

    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self.accepted = 0
        self.closed_by_client = 0
        self.received = b""  # bytes the client sent after the handler finished
        self._writers: list[asyncio.StreamWriter] = []

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.accepted += 1
        self._writers.append(writer)
        try:
            await self._handler(reader, writer)
            while data := await reader.read(1024):  # never answer; wait for the client to give up
                self.received += data
            self.closed_by_client += 1
        finally:
            writer.close()

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        return int(self.server.sockets[0].getsockname()[1])

    async def stop(self) -> None:
        self.server.close()
        for writer in self._writers:
            writer.close()
        await self.server.wait_closed()


async def silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Accept the TCP connection, then say nothing (connect phase hangs)."""


async def authenticated_then_silent(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    """Complete the startup handshake, then never answer a query (query phase hangs)."""
    length = struct.unpack("!I", await reader.readexactly(4))[0]
    request = await reader.readexactly(length - 4)
    if struct.unpack("!I", request[:4])[0] == 80877103:  # SSLRequest
        writer.write(b"N")
        await writer.drain()
        length = struct.unpack("!I", await reader.readexactly(4))[0]
        await reader.readexactly(length - 4)
    writer.write(b"R" + struct.pack("!II", 8, 0))  # AuthenticationOk
    writer.write(b"S" + struct.pack("!I", 4 + 3) + b"a\x00\x00")  # ParameterStatus
    writer.write(b"K" + struct.pack("!III", 12, 1, 1))  # BackendKeyData
    writer.write(b"Z" + struct.pack("!I", 5) + b"I")  # ReadyForQuery
    await writer.drain()


def settings_for(port: int) -> Settings:
    return Settings(
        database_url=f"postgresql+psycopg://u:p@127.0.0.1:{port}/db",
        readiness_timeout_seconds=TIMEOUT,
    )


async def ready(client: httpx.AsyncClient) -> tuple[httpx.Response, float]:
    started = time.perf_counter()
    response = await client.get("/health/ready")
    return response, time.perf_counter() - started


def make_app(head: str | None = "head1") -> FastAPI:
    app = create_app()
    app.state.expected_head = head  # what the lifespan would have stored
    return app


def async_client(app: FastAPI | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app or make_app()), base_url="http://testserver"
    )


@pytest.mark.parametrize("handler", [silent, authenticated_then_silent])
def test_ready_returns_503_by_the_deadline_and_releases_the_connection(
    handler: Handler, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        hole = BlackHole(handler)
        port = await hole.start()
        monkeypatch.setattr(health, "get_settings", lambda: settings_for(port))
        app = make_app()
        try:
            async with async_client(app) as client:
                response, elapsed = await ready(client)
            assert response.status_code == 503
            assert elapsed < TIMEOUT + MARGIN
            assert "127.0.0.1" not in response.text
            await asyncio.sleep(0.2)
            assert hole.accepted == 1
            assert hole.closed_by_client == 1  # client closed its socket after the timeout
            if handler is authenticated_then_silent:
                assert b"SELECT 1" in hole.received  # it really hung in the query phase
            inflight = app.state.readiness_inflight
            assert inflight is not None and inflight.done()
        finally:
            await hole.stop()
        leftovers = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        assert leftovers == []

    asyncio.run(scenario())


def test_concurrent_probes_share_one_database_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        hole = BlackHole(silent)
        port = await hole.start()
        monkeypatch.setattr(health, "get_settings", lambda: settings_for(port))
        try:
            async with async_client() as client:
                results = await asyncio.gather(*(ready(client) for _ in range(6)))
            assert {response.status_code for response, _ in results} == {503}
            assert max(elapsed for _, elapsed in results) < TIMEOUT + MARGIN
            assert hole.accepted == 1
        finally:
            await hole.stop()

    asyncio.run(scenario())


def test_live_is_not_blocked_by_a_hung_readiness_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        hole = BlackHole(silent)
        port = await hole.start()
        monkeypatch.setattr(health, "get_settings", lambda: settings_for(port))
        try:
            async with async_client() as client:
                slow = asyncio.create_task(ready(client))
                await asyncio.sleep(0.05)
                started = time.perf_counter()
                live = await client.get("/health/live")
                assert live.status_code == 200
                assert time.perf_counter() - started < TIMEOUT / 2
                await slow
        finally:
            await hole.stop()

    asyncio.run(scenario())


async def refuses_tls(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Server without TLS: answer the SSLRequest with 'N'."""
    length = struct.unpack("!I", await reader.readexactly(4))[0]
    await reader.readexactly(length - 4)
    writer.write(b"N")
    await writer.drain()


@pytest.mark.parametrize("sslmode", ["require", "verify-full"])
def test_probe_never_downgrades_tls_and_never_sends_the_password(sslmode: str) -> None:
    async def scenario() -> None:
        hole = BlackHole(refuses_tls)
        port = await hole.start()
        settings = Settings(
            database_url=(
                f"postgresql+psycopg://probe-user:pw-needle-4471@127.0.0.1:{port}/db"
                f"?sslmode={sslmode}"
            ),
            readiness_timeout_seconds=TIMEOUT,
        )
        try:
            state = await readiness.fetch_database_state(settings)
            await asyncio.sleep(0.1)
        finally:
            await hole.stop()
        assert state.reachable is False
        assert hole.accepted == 1
        assert b"pw-needle-4471" not in hole.received
        assert b"probe-user" not in hole.received  # not even the startup packet was sent
        assert hole.received == b""

    asyncio.run(scenario())


def test_plain_url_still_proceeds_with_startup_after_tls_is_declined() -> None:
    async def scenario() -> None:
        hole = BlackHole(refuses_tls)
        port = await hole.start()
        try:
            await readiness.fetch_database_state(settings_for(port))
            await asyncio.sleep(0.1)
        finally:
            await hole.stop()
        assert b"user" in hole.received  # default sslmode=prefer: behaviour unchanged

    asyncio.run(scenario())


def test_cancelling_the_shared_evaluation_closes_the_connection_without_a_cancel_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        hole = BlackHole(authenticated_then_silent)
        port = await hole.start()
        settings = Settings(
            database_url=f"postgresql+psycopg://u:p@127.0.0.1:{port}/db",
            readiness_timeout_seconds=5,  # long: only the cancellation may end this
        )
        state = SimpleNamespace()
        caller = asyncio.create_task(readiness.run_readiness(settings, "head1", state))
        try:
            for _ in range(100):
                if b"SELECT 1" in hole.received:
                    break
                await asyncio.sleep(0.02)
            assert b"SELECT 1" in hole.received
            shared = state.readiness_inflight
            assert shared is not None
            started = time.perf_counter()
            shared.cancel()
            await asyncio.wait({shared}, timeout=2)
            assert time.perf_counter() - started < 1.0
            await asyncio.sleep(0.2)
            assert hole.closed_by_client == 1
            assert hole.accepted == 1  # no extra connection for a server-side cancel request
            caller.cancel()
            await asyncio.wait({caller}, timeout=1)
        finally:
            await hole.stop()
        assert [t for t in asyncio.all_tasks() if t is not asyncio.current_task()] == []

    asyncio.run(scenario())


def test_total_evaluation_budget_holds_even_if_a_step_ignores_its_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def never_returns(_: Settings) -> DatabaseState:
        await asyncio.sleep(3600)
        raise AssertionError

    monkeypatch.setattr(readiness, "fetch_database_state", never_returns)
    monkeypatch.setattr(health, "get_settings", lambda: settings_for(1))

    async def scenario() -> None:
        async with async_client() as client:
            response, elapsed = await ready(client)
        assert response.status_code == 503
        assert elapsed < TIMEOUT + readiness.EVALUATION_GRACE_SECONDS + MARGIN

    asyncio.run(scenario())


async def healthy(_: Settings) -> DatabaseState:
    return DatabaseState(True, ("head1",))


def test_unreadable_head_keeps_ready_failed_until_restart_but_live_stays_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def compute() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("scripts missing")
        return "head1"  # would succeed on a second attempt; there must not be one

    monkeypatch.setattr(readiness, "_compute_head", compute)
    monkeypatch.setattr(readiness, "fetch_database_state", healthy)
    monkeypatch.setattr(health, "get_settings", lambda: Settings())

    with TestClient(create_app()) as client:  # runs the lifespan
        for _ in range(3):
            response = client.get("/health/ready")
            assert response.status_code == 503
            assert response.json()["checks"]["migrations"] == "fail"
            assert client.get("/health/live").status_code == 200
        assert calls == [1]  # read once at startup, never retried or read on a request

    with TestClient(create_app()) as restarted:  # "restart": a fresh lifespan
        assert restarted.get("/health/ready").status_code == 200


def test_head_is_read_off_the_event_loop_without_blocking_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    threads: list[int] = []

    def slow_compute() -> str:
        threads.append(threading.get_ident())
        time.sleep(0.3)
        return "head1"

    monkeypatch.setattr(readiness, "_compute_head", slow_compute)

    async def scenario() -> None:
        gaps: list[float] = []

        async def heartbeat() -> None:
            while True:
                before = time.perf_counter()
                await asyncio.sleep(0.01)
                gaps.append(time.perf_counter() - before)

        beat = asyncio.create_task(heartbeat())
        try:
            assert await readiness.load_expected_head() == "head1"
        finally:
            beat.cancel()
        assert max(gaps) < 0.2
        assert threads and threads[0] != threading.get_ident()

    asyncio.run(scenario())


def test_two_app_instances_do_not_share_head_or_inflight_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(readiness, "fetch_database_state", healthy)
    monkeypatch.setattr(health, "get_settings", lambda: Settings())

    async def scenario() -> None:
        good, broken = make_app("head1"), make_app(None)
        async with async_client(good) as good_client, async_client(broken) as broken_client:
            assert (await good_client.get("/health/ready")).status_code == 200
            assert (await broken_client.get("/health/ready")).status_code == 503
            assert (await good_client.get("/health/ready")).status_code == 200
        assert good.state.readiness_inflight is not broken.state.readiness_inflight

    asyncio.run(scenario())
