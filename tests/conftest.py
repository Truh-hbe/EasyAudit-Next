import socket
import struct
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import boto3
import pytest
from botocore.config import Config
from moto.server import ThreadedMotoServer

from easyaudit_next.platform.settings import Settings

ACCESS_KEY = "GKtestaccesskey000000000000"
SECRET_KEY = "test-secret-key-never-logged-7f3a91"


@dataclass(frozen=True, slots=True)
class FakeS3:
    endpoint: str
    bucket: str
    access_key: str
    secret_key: str
    access_key_file: Path
    secret_key_file: Path

    def client(self):  # type: ignore[no-untyped-def]
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            region_name="garage",
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=Config(proxies={}),
        )

    def settings(self, **overrides: object) -> Settings:
        values: dict[str, object] = {
            "object_storage_endpoint": self.endpoint,
            "object_storage_bucket": self.bucket,
            "object_storage_access_key_id_file": str(self.access_key_file),
            "object_storage_secret_access_key_file": str(self.secret_key_file),
        }
        return Settings(**{**values, **overrides})  # type: ignore[arg-type]

    def keys(self) -> list[str]:
        pages = self.client().get_paginator("list_objects_v2").paginate(Bucket=self.bucket)
        return [item["Key"] for page in pages for item in page.get("Contents", [])]

    def open_uploads(self) -> list[str]:
        response = self.client().list_multipart_uploads(Bucket=self.bucket)
        return [item["UploadId"] for item in response.get("Uploads", [])]


@pytest.fixture(scope="session")
def moto_endpoint() -> Iterator[str]:
    """A real in-process S3 server on a loopback port: botocore speaks real HTTP to it."""
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


@pytest.fixture
def fake_s3(moto_endpoint: str, tmp_path: Path) -> FakeS3:
    access_key_file = tmp_path / "s3_access_key_id"
    secret_key_file = tmp_path / "s3_secret_access_key"
    access_key_file.write_text(ACCESS_KEY)
    secret_key_file.write_text(SECRET_KEY + "\n")
    fake = FakeS3(
        moto_endpoint,
        f"evidence-{uuid4().hex[:12]}",
        ACCESS_KEY,
        SECRET_KEY,
        access_key_file,
        secret_key_file,
    )
    fake.client().create_bucket(
        Bucket=fake.bucket, CreateBucketConfiguration={"LocationConstraint": "garage"}
    )
    return fake


class SilentTcpServer:
    """A hostile TCP endpoint. `silent` accepts and never answers; `drip` answers one byte of an
    endless status line every 50 ms (a total deadline matters, per-read timeouts never fire);
    `reset` accepts and immediately resets the connection."""

    def __init__(self, mode: str = "silent") -> None:
        self._mode = mode
        self._server = socket.socket()
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(16)
        self._accepted: list[socket.socket] = []
        self._closed = False
        self.endpoint = f"http://127.0.0.1:{self._server.getsockname()[1]}"
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while True:
            try:
                connection, _ = self._server.accept()
            except OSError:
                return
            self._accepted.append(connection)
            if self._mode == "reset":
                connection.setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                )
                connection.close()
            elif self._mode == "drip":
                threading.Thread(target=self._drip, args=(connection,), daemon=True).start()

    def _drip(self, connection: socket.socket) -> None:
        try:
            for byte in b"HTTP/1.1 200 OK" + b"x" * 10_000:
                if self._closed:
                    return
                connection.sendall(bytes([byte]))
                time.sleep(0.05)
        except OSError:
            return

    def close(self) -> None:
        self._closed = True
        self._server.close()
        for connection in self._accepted:
            connection.close()


@pytest.fixture
def silent_server() -> Iterator[SilentTcpServer]:
    server = SilentTcpServer()
    yield server
    server.close()


@pytest.fixture(params=["silent", "drip", "reset"])
def hostile_server(request: pytest.FixtureRequest) -> Iterator[SilentTcpServer]:
    server = SilentTcpServer(request.param)
    yield server
    server.close()
