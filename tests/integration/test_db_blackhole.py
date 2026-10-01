"""A database that accepts TCP and then never answers must not hang threads forever."""

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from easyaudit_next import main
from easyaudit_next.infrastructure import readiness
from easyaudit_next.infrastructure.database import create_database_engine
from easyaudit_next.platform.settings import Settings

CONNECT_TIMEOUT = 1


@pytest.fixture
def blackhole_url() -> Iterator[str]:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(16)
    accepted: list[socket.socket] = []
    stop = threading.Event()

    def accept_forever() -> None:
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                accepted.append(server.accept()[0])  # hold the socket open, never reply
            except OSError:
                continue

    thread = threading.Thread(target=accept_forever, daemon=True)
    thread.start()
    yield f"postgresql+psycopg://u:p@127.0.0.1:{server.getsockname()[1]}/db"
    stop.set()
    thread.join(timeout=2)
    for connection in accepted:
        connection.close()
    server.close()


def test_verification_fails_within_connect_timeout_and_retries(
    blackhole_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(database_url=blackhole_url, db_connect_timeout_seconds=CONNECT_TIMEOUT)
    engine = create_database_engine(settings)
    monkeypatch.setattr(readiness, "DB_SETTINGS_RETRY_SECONDS", 0.1)
    calls: list[tuple[float, float]] = []
    real = readiness.verify_server_settings

    def timed(*args: object) -> object:
        started = time.monotonic()
        try:
            return real(*args)  # type: ignore[arg-type]
        finally:
            calls.append((started, time.monotonic()))

    monkeypatch.setattr(readiness, "verify_server_settings", timed)
    state = SimpleNamespace()

    async def scenario() -> None:
        task = asyncio.create_task(readiness.verify_db_settings(state, engine, settings))
        await asyncio.sleep(CONNECT_TIMEOUT * 2 + 1.5)
        task.cancel()
        await asyncio.wait({task}, timeout=CONNECT_TIMEOUT + 3)

    try:
        asyncio.run(scenario())
    finally:
        engine.dispose()

    assert len(calls) >= 2  # failed, then retried
    assert all(end - start < CONNECT_TIMEOUT + 1.5 for start, end in calls)
    assert state.db_settings_failures is None  # still unverified: readiness stays failed


def test_lifespan_exit_is_bounded_when_the_database_is_a_black_hole(
    blackhole_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(database_url=blackhole_url, db_connect_timeout_seconds=CONNECT_TIMEOUT)
    engine = create_database_engine(settings)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "get_business_engine", lambda: engine)

    started = time.monotonic()
    try:
        with TestClient(main.create_app()):
            time.sleep(0.3)  # the verification is now stuck connecting
        elapsed = time.monotonic() - started
    finally:
        engine.dispose()

    assert elapsed < CONNECT_TIMEOUT + 4
