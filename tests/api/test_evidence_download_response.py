"""The download response in isolation: the object is closed on every way a response can end."""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from easyaudit_next.api.review_evidence_downloads import (
    EvidenceDownloadResponse,
    content_disposition,
)
from easyaudit_next.review_core.application.evidence_storage import ObjectStoreError
from easyaudit_next.review_core.domain.models import Evidence
from tests.evidence_support import FakeEvidenceStore

DATA = b"0123456789" * 10


def evidence(key: str = "org/o/evidence/k") -> Evidence:
    return Evidence(
        id=uuid4(), organization_id=uuid4(), action_item_id=uuid4(), storage_key=key,
        original_name="a.pdf", content_type="application/pdf", size_bytes=len(DATA),
        sha256="0" * 64, description=None, uploaded_by=uuid4(), created_at=datetime.now(UTC),
    )  # fmt: skip


def scope(spec_version: str) -> dict[str, Any]:
    return {"type": "http", "asgi": {"version": "3.0", "spec_version": spec_version}}


def test_filename_fallback_is_plain_ascii_and_filename_star_is_percent_encoded() -> None:
    header = content_disposition('报告 "final";v1%.pdf')

    assert header.startswith('attachment; filename="__ _final__v1_.pdf"; filename*=UTF-8\'\'')
    assert header.endswith("%E6%8A%A5%E5%91%8A%20%22final%22%3Bv1%25.pdf")
    assert header.isascii()


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
def test_a_client_that_disconnects_mid_download_gets_the_object_closed(spec_version: str) -> None:
    store = FakeEvidenceStore(download_chunk_size=10)
    ev = evidence()
    store.objects[ev.storage_key] = DATA
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        while len(sent) < 3:  # headers and the first chunk are out; now the client leaves
            await asyncio.sleep(0)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)
        if spec_version == "2.4" and len(sent) == 3:
            raise OSError("client gone")  # what uvicorn does for spec >= 2.4

    asyncio.run(EvidenceDownloadResponse(store, ev)(scope(spec_version), receive, send))

    [stream] = store.streams
    assert stream.closed
    assert stream.chunks_served < len(DATA) // 10  # it stopped early


def test_a_completed_download_closes_the_object_and_sends_every_byte() -> None:
    store = FakeEvidenceStore(download_chunk_size=7)
    ev = evidence()
    store.objects[ev.storage_key] = DATA
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        await asyncio.Event().wait()
        raise AssertionError

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(EvidenceDownloadResponse(store, ev)(scope("2.3"), receive, send))

    assert b"".join(m.get("body", b"") for m in sent) == DATA
    assert store.streams[0].closed


def test_a_store_error_while_opening_is_a_503_and_not_a_404() -> None:
    class Down(FakeEvidenceStore):
        async def open_stream(self, key: str) -> Any:
            raise ObjectStoreError("down")

    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(EvidenceDownloadResponse(Down(), evidence())(scope("2.4"), receive, send))

    assert sent[0]["status"] == 503
