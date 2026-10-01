"""Request-level behaviour of the upload route. Authorization and registration are stubbed
(they have PostgreSQL tests); everything about headers, limits and the store is real."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from easyaudit_next.api import review_evidence_uploads as uploads
from easyaudit_next.api.dependencies import (
    CurrentIdentity,
    get_current_identity,
    get_database_session,
    require_business_identity,
)
from easyaudit_next.main import create_app
from easyaudit_next.platform.domain.ids import AuthSessionId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import AuthSession, PlatformRole, User
from easyaudit_next.review_core.application.evidence_policy import EvidenceUploadPolicy
from easyaudit_next.review_core.domain.models import Evidence
from tests.evidence_support import FakeEvidenceStore

ACTION_ID = uuid4()
URL = f"/api/v1/action-items/{ACTION_ID}/evidence-uploads"
PDF = {"Content-Type": "application/pdf", "X-Evidence-Filename": "report.pdf"}
NOW = datetime(2026, 10, 1, tzinfo=UTC)
USER = User(
    id=UserId(uuid4()),
    organization_id=OrganizationId(uuid4()),
    display_name="Owner",
    platform_role=PlatformRole.ORDINARY_USER,
    primary_department_id=None,
)


class Recorder:
    def __init__(self) -> None:
        self.preauthorized = 0
        self.registered: list[dict[str, Any]] = []


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()

    def preauthorize(*_: object) -> None:
        recorder.preauthorized += 1

    def register(
        session: object, actor_id: Any, action_id: Any, key: str, file: Any, size: int,
        sha256: str, description: str | None,
    ) -> Evidence:  # fmt: skip
        recorder.registered.append(
            {"key": key, "name": file.original_name, "type": file.content_type, "size": size,
             "sha256": sha256, "description": description}
        )  # fmt: skip
        return Evidence(
            id=uuid4(), organization_id=USER.organization_id, action_item_id=action_id,
            storage_key=key, original_name=file.original_name, content_type=file.content_type,
            size_bytes=size, sha256=sha256, description=description, uploaded_by=actor_id,
            created_at=NOW,
        )  # fmt: skip

    monkeypatch.setattr(uploads, "_preauthorize", preauthorize)
    monkeypatch.setattr(uploads, "_register", register)
    return recorder


@pytest.fixture
def store() -> FakeEvidenceStore:
    return FakeEvidenceStore()


def make_client(store: FakeEvidenceStore | None, max_bytes: int = 1024) -> Iterator[TestClient]:
    app = create_app()
    identity = CurrentIdentity(
        auth_session=AuthSession(
            id=AuthSessionId(uuid4()),
            organization_id=USER.organization_id,
            user_id=USER.id,
            token_hash="a" * 64,
            expires_at=NOW + timedelta(hours=1),
            created_at=NOW,
        ),
        user=USER,
    )
    app.dependency_overrides[get_current_identity] = lambda: identity
    app.dependency_overrides[require_business_identity] = lambda: identity
    app.dependency_overrides[get_database_session] = lambda: MagicMock()
    app.dependency_overrides[uploads.get_evidence_upload_policy] = lambda: (
        EvidenceUploadPolicy.from_config(max_bytes, "application/pdf,text/csv")
    )
    if store is not None:
        app.dependency_overrides[uploads.get_evidence_object_store] = lambda: store
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(store: FakeEvidenceStore, recorder: Recorder) -> Iterator[TestClient]:
    yield from make_client(store)


def test_server_computes_size_sha_and_key_from_the_streamed_bytes(
    client: TestClient, store: FakeEvidenceStore, recorder: Recorder
) -> None:
    import hashlib

    content = b"%PDF-1.7 evidence bytes" * 20

    response = client.post(
        URL,
        content=content,
        headers={**PDF, "X-Evidence-Filename": "%E6%95%B4%E6%94%B9.pdf"},
        params={"description": "after photo"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["size_bytes"] == len(content)
    assert body["sha256"] == hashlib.sha256(content).hexdigest()
    assert body["original_name"] == "整改.pdf"
    assert body["content_type"] == "application/pdf"
    assert body["description"] == "after photo"
    assert list(store.objects) == [body["storage_key"]]
    assert store.objects[body["storage_key"]] == content
    assert body["storage_key"].startswith(f"org/{USER.organization_id}/evidence/")
    assert "整改" not in body["storage_key"] and "report" not in body["storage_key"]


def test_client_cannot_choose_key_sha_or_size(
    client: TestClient, store: FakeEvidenceStore, recorder: Recorder
) -> None:
    import hashlib

    content = b"real content"

    response = client.post(
        URL,
        content=content,
        headers={
            **PDF,
            "X-Evidence-Storage-Key": "org/other/evidence/stolen",
            "X-Evidence-Sha256": "0" * 64,
            "X-Evidence-Size": "1",
        },
        params={"storage_key": "org/other/evidence/stolen", "sha256": "0" * 64, "size_bytes": 1},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["storage_key"] != "org/other/evidence/stolen"
    assert body["sha256"] == hashlib.sha256(content).hexdigest()
    assert body["size_bytes"] == len(content)
    assert "stolen" not in " ".join(store.objects)


def test_a_json_registration_body_is_not_a_way_to_register(
    client: TestClient, store: FakeEvidenceStore
) -> None:
    response = client.post(
        f"/api/v1/action-items/{ACTION_ID}/evidences",
        json={"storage_key": "k", "original_name": "a.pdf", "size_bytes": 1, "sha256": "0" * 64},
    )

    assert response.status_code == 405
    assert store.put_calls == []


def test_content_length_over_the_limit_is_refused_without_reading_or_writing(
    client: TestClient, store: FakeEvidenceStore, recorder: Recorder
) -> None:
    response = client.post(URL, content=b"x" * 1025, headers=PDF)

    assert response.status_code == 413
    assert store.put_calls == [] and store.objects == {}
    assert recorder.registered == []


def test_streamed_body_over_the_limit_is_aborted_with_nothing_left(
    client: TestClient, store: FakeEvidenceStore, recorder: Recorder
) -> None:
    def body() -> Iterator[bytes]:  # no Content-Length: chunked transfer encoding
        for _ in range(8):
            yield b"x" * 200

    response = client.post(URL, content=body(), headers=PDF)

    assert response.status_code == 413
    assert store.put_calls != [] and store.objects == {}
    assert recorder.registered == []


def test_body_exactly_at_the_limit_is_accepted(
    client: TestClient, store: FakeEvidenceStore
) -> None:
    assert client.post(URL, content=b"x" * 1024, headers=PDF).status_code == 201


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Type": "application/octet-stream", "X-Evidence-Filename": "a.pdf"},
        {"Content-Type": "image/png", "X-Evidence-Filename": "a.png"},  # real but not listed
        {"Content-Type": "application/pdf", "X-Evidence-Filename": "a.exe"},
        {"Content-Type": "application/pdf", "X-Evidence-Filename": "noextension"},
        {"X-Evidence-Filename": "a.pdf"},
    ],
)
def test_types_outside_the_policy_get_415_and_nothing_is_written(
    client: TestClient, store: FakeEvidenceStore, recorder: Recorder, headers: dict[str, str]
) -> None:
    headers = dict(headers)
    response = client.post(URL, content=b"data", headers={"Content-Type": "", **headers})

    assert response.status_code == 415
    assert store.put_calls == [] and recorder.registered == []


def test_missing_or_unusable_filename_is_rejected(
    client: TestClient, store: FakeEvidenceStore
) -> None:
    missing = client.post(URL, content=b"data", headers={"Content-Type": "application/pdf"})
    unusable = client.post(URL, content=b"data", headers={**PDF, "X-Evidence-Filename": ".."})
    bad_encoding = client.post(URL, content=b"data", headers={**PDF, "X-Evidence-Filename": "%FF"})

    assert (missing.status_code, unusable.status_code, bad_encoding.status_code) == (422, 422, 422)
    assert store.put_calls == []


def test_path_components_in_the_filename_never_reach_the_key(
    client: TestClient, store: FakeEvidenceStore
) -> None:
    response = client.post(
        URL, content=b"data", headers={**PDF, "X-Evidence-Filename": "..%2F..%2Fetc%2Fpasswd.pdf"}
    )

    assert response.status_code == 201
    assert response.json()["original_name"] == "passwd.pdf"
    assert "passwd" not in response.json()["storage_key"]


def test_empty_upload_is_rejected_and_leaves_nothing(
    client: TestClient, store: FakeEvidenceStore, recorder: Recorder
) -> None:
    declared = client.post(URL, content=b"", headers=PDF)

    def empty_chunked() -> Iterator[bytes]:
        yield b""

    chunked = client.post(URL, content=empty_chunked(), headers=PDF)

    assert declared.status_code == 422 and chunked.status_code == 422
    assert store.objects == {} and recorder.registered == []


def test_register_failure_deletes_the_object_and_returns_the_original_error(
    client: TestClient, store: FakeEvidenceStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def register(*_: object) -> Evidence:
        raise ValueError("Evidence cannot be registered for a cancelled ActionItem")

    monkeypatch.setattr(uploads, "_register", register)

    response = client.post(URL, content=b"data", headers=PDF)

    assert response.status_code == 422
    assert "cancelled ActionItem" in response.json()["detail"]
    assert store.objects == {} and len(store.deleted) == 1


def test_unconfigured_object_storage_is_503_before_anything_happens(
    recorder: Recorder,
) -> None:
    for client in make_client(None):
        response = client.post(URL, content=b"data", headers=PDF)

    assert response.status_code == 503
    assert recorder.preauthorized == 0


def test_object_store_failure_is_503_and_registers_nothing(
    client: TestClient, store: FakeEvidenceStore, recorder: Recorder
) -> None:
    from easyaudit_next.review_core.application.evidence_storage import ObjectStoreError

    async def failing_put(key: str, chunks: Any) -> Any:
        raise ObjectStoreError("Object storage operation failed")

    store.put_stream = failing_put  # type: ignore[method-assign]

    response = client.post(URL, content=b"data", headers=PDF)

    assert response.status_code == 503
    assert recorder.registered == []
