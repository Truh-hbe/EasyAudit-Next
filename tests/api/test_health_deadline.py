"""Readiness must return by its own deadline even when the database never answers."""

import asyncio
import struct
import time
from collections.abc import Awaitable, Callable

import httpx
import pytest

from easyaudit_next.api import health
from easyaudit_next.infrastructure import readiness
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


def async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver"
    )


@pytest.mark.parametrize("handler", [silent, authenticated_then_silent])
def test_ready_returns_503_by_the_deadline_and_releases_the_connection(
    handler: Handler, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        hole = BlackHole(handler)
        port = await hole.start()
        monkeypatch.setattr(health, "get_settings", lambda: settings_for(port))
        monkeypatch.setattr(health, "get_expected_head", lambda: "head1")
        try:
            async with async_client() as client:
                response, elapsed = await ready(client)
            assert response.status_code == 503
            assert elapsed < TIMEOUT + MARGIN
            assert "127.0.0.1" not in response.text
            await asyncio.sleep(0.2)
            assert hole.accepted == 1
            assert hole.closed_by_client == 1  # client closed its socket after the timeout
            if handler is authenticated_then_silent:
                assert b"SELECT 1" in hole.received  # it really hung in the query phase
            inflight = readiness._inflight
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
        monkeypatch.setattr(health, "get_expected_head", lambda: "head1")
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
        monkeypatch.setattr(health, "get_expected_head", lambda: "head1")
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
