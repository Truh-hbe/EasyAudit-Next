"""A database that accepts TCP and then never answers must not hang connection setup."""

import socket
import threading
import time
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

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


def test_business_engine_connect_fails_within_connect_timeout(blackhole_url: str) -> None:
    engine = create_database_engine(
        Settings(database_url=blackhole_url, db_connect_timeout_seconds=CONNECT_TIMEOUT)
    )
    started = time.monotonic()
    try:
        with pytest.raises(OperationalError), engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()

    assert time.monotonic() - started < CONNECT_TIMEOUT + 2
