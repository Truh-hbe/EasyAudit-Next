"""Run the real server entry point and scan everything the process writes."""

import base64
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator

import pytest

TOKEN = "query-token-needle-6021"
COOKIE = "cookie-needle-7754"
AUTHORIZATION = "Bearer authorization-needle-3390"
PASSWORD = "password-needle-1187"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def raw_request(port: int, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
        sock.sendall(request)
        chunks = []
        try:
            while chunk := sock.recv(4096):
                chunks.append(chunk)
        except TimeoutError:
            pass
        return b"".join(chunks)


@pytest.fixture(params=["INFO", "DEBUG"])
def server(request: pytest.FixtureRequest) -> Iterator[tuple[int, subprocess.Popen[str]]]:
    port = free_port()
    env = {
        **os.environ,
        "APP_HOST": "127.0.0.1",
        "APP_PORT": str(port),
        "LOG_LEVEL": request.param,
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "easyaudit_next.serve"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        # Raw socket, not urllib: urllib honours system proxy settings (e.g. on macOS).
        try:
            reply = raw_request(
                port, b"GET /health/live HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"
            )
        except OSError:
            reply = b""
        if b" 200 " in reply.split(b"\r\n", 1)[0]:
            break
        time.sleep(0.2)
    else:
        process.kill()
        pytest.fail(f"server did not start: {process.communicate()[0][-3000:]}")
    yield port, process
    if process.poll() is None:
        process.terminate()


def test_no_protocol_or_access_output_leaks_secrets(
    server: tuple[int, subprocess.Popen[str]],
) -> None:
    port, process = server
    websocket_key = base64.b64encode(b"0123456789abcdef").decode()
    headers = (
        f"Host: 127.0.0.1:{port}\r\n"
        f"Cookie: __Host-easyaudit_session={COOKIE}\r\n"
        f"Authorization: {AUTHORIZATION}\r\n"
    )
    upgrade = (
        f"GET /api/v1/not-a-ws?token={TOKEN} HTTP/1.1\r\n{headers}"
        f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {websocket_key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    ).encode()
    plain = (
        f"GET /api/v1/me?token={TOKEN}&password={PASSWORD} HTTP/1.1\r\n{headers}"
        f"Connection: close\r\n\r\n"
    ).encode()
    malformed = f"GET /{TOKEN} \x00 HTTP/9.9\r\nCookie: {COOKIE}\r\n\r\n".encode()

    raw_request(port, upgrade)
    raw_request(port, plain)
    raw_request(port, malformed)
    process.terminate()
    output, _ = process.communicate(timeout=15)

    assert '"logger": "easyaudit.access"' in output  # the plain request was logged
    for secret in (TOKEN, COOKIE, AUTHORIZATION, "authorization-needle", PASSWORD):
        assert secret not in output
    for line in output.splitlines():
        assert line.startswith("{"), f"non-JSON output line: {line[:80]}"
