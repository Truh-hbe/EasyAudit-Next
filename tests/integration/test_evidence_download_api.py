"""Evidence download against real PostgreSQL, with an in-memory object store.

Authorization is the same read permission as listing the Action's Evidence, looked up by
`(organization, evidence)`. Every refusal is the same 404 and never reaches the store; the
transaction is over before the first byte is streamed; a missing object is a loud 500.
"""

import hashlib
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from easyaudit_next.api import review_evidence_downloads as downloads
from easyaudit_next.api.dependencies import get_database_session, get_session_factory
from easyaudit_next.main import create_app
from easyaudit_next.platform.persistence.models import LocalCredentialRecord
from easyaudit_next.platform.settings import get_settings
from easyaudit_next.review_core.persistence.models import EvidenceRecord
from tests.evidence_support import FakeEvidenceStore
from tests.integration.test_credential_readiness import PASSWORD_HASH, _login
from tests.integration.test_credential_readiness import postgres_engine as postgres_engine
from tests.integration.test_evidence_upload_api import (
    client_for as upload_client_for,
)
from tests.integration.test_evidence_upload_api import (
    idle_in_transaction_connections,
)
from tests.integration.test_review_resource_queries import (
    SeededCollaboration,
    _seed_collaboration_shape,
)


@pytest.fixture
def seeded(postgres_engine: Engine) -> SeededCollaboration:
    return _seed_collaboration_shape(postgres_engine)


def seed_evidence(
    engine: Engine,
    seeded: SeededCollaboration,
    store: FakeEvidenceStore,
    content: bytes = b"%PDF-1.7 torque record\n" * 40,
    *,
    name: str = "torque-record.pdf",
    content_type: str | None = "application/pdf",
    put: bool = True,
) -> EvidenceRecord:
    key = f"org/{seeded.organization_id}/evidence/{uuid4()}"
    if put:
        store.objects[key] = content
    record = EvidenceRecord(
        id=uuid4(),
        organization_id=seeded.organization_id,
        action_item_id=seeded.action_id,
        storage_key=key,
        original_name=name,
        content_type=content_type,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        description=None,
        uploaded_by=seeded.owner_id,
        created_at=datetime.now(UTC),
    )
    with Session(engine, expire_on_commit=False) as session, session.begin():
        session.add(record)
    return record


def client_for(
    engine: Engine,
    seeded: SeededCollaboration,
    user_id: Any,
    store: FakeEvidenceStore | None,
    **kwargs: Any,
) -> Iterator[TestClient]:
    """`store=None` stands for "object storage is not configured"."""
    stand_in = store or FakeEvidenceStore()
    for client in upload_client_for(engine, seeded, user_id, stand_in, **kwargs):
        app: Any = client.app
        app.dependency_overrides[downloads.get_optional_evidence_store] = lambda: store
        yield client


def url(evidence: EvidenceRecord) -> str:
    return f"/api/v1/evidences/{evidence.id}/content"


def test_users_who_can_read_the_evidence_list_get_the_exact_bytes(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    store = FakeEvidenceStore()
    content = bytes(range(256)) * 20
    evidence = seed_evidence(postgres_engine, seeded, store, content)

    for user_id in (seeded.owner_id, seeded.assignee_id, seeded.lead_id):
        for client in client_for(postgres_engine, seeded, user_id, store):
            response = client.get(url(evidence))
            listing = client.get(f"/api/v1/action-items/{seeded.action_id}/evidences")
        assert listing.status_code == 200  # the permission being mirrored
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == evidence.sha256
        assert response.content == content


def test_download_permission_is_exactly_the_list_permission(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    store = FakeEvidenceStore()
    evidence = seed_evidence(postgres_engine, seeded, store)

    for user_id in (
        seeded.owner_id,
        seeded.assignee_id,
        seeded.lead_id,
        seeded.candidate_id,
        seeded.unrelated_id,
        seeded.admin_id,
    ):
        for client in client_for(postgres_engine, seeded, user_id, store):
            listed = client.get(f"/api/v1/action-items/{seeded.action_id}/evidences")
            downloaded = client.get(url(evidence))
        assert (listed.status_code == 200) == (downloaded.status_code == 200), user_id
        assert downloaded.status_code in {200, 404}


def test_refused_unknown_and_foreign_requests_are_one_404_and_never_touch_the_store(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    store = FakeEvidenceStore()
    evidence = seed_evidence(postgres_engine, seeded, store)
    foreign = _seed_collaboration_shape(postgres_engine)
    for client in client_for(postgres_engine, seeded, seeded.unrelated_id, store):
        unrelated = client.get(url(evidence))
        unknown = client.get(f"/api/v1/evidences/{uuid4()}/content")
    for client in client_for(
        postgres_engine, seeded, foreign.owner_id, store, organization_id=foreign.organization_id
    ):
        cross_organization = client.get(url(evidence))
    responses = [unrelated, unknown, cross_organization]
    assert [r.status_code for r in responses] == [404, 404, 404]
    assert {r.json()["detail"] for r in responses} == {"Evidence not found"}
    assert store.open_calls == [] and store.streams == []


def test_knowing_the_storage_key_does_not_help(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    store = FakeEvidenceStore()
    evidence = seed_evidence(postgres_engine, seeded, store)

    for client in client_for(postgres_engine, seeded, seeded.unrelated_id, store):
        by_key = client.get(f"/api/v1/evidences/{evidence.storage_key}/content")
        encoded = quote(evidence.storage_key, safe="")
        by_encoded_key = client.get(f"/api/v1/evidences/{encoded}/content")

    assert by_key.status_code in {404, 422} and by_encoded_key.status_code in {404, 422}
    assert store.open_calls == []


def test_headers_for_a_chinese_file_name(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    store = FakeEvidenceStore()
    evidence = seed_evidence(postgres_engine, seeded, store, name="整改记录 v2.pdf")

    for client in client_for(postgres_engine, seeded, seeded.owner_id, store):
        response = client.get(url(evidence))

    assert response.headers["content-disposition"] == (
        'attachment; filename="____ v2.pdf"; '
        "filename*=UTF-8''%E6%95%B4%E6%94%B9%E8%AE%B0%E5%BD%95%20v2.pdf"
    )
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-length"] == str(evidence.size_bytes)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert response.headers["x-request-id"]


def test_quotes_and_semicolons_in_the_name_cannot_break_out_of_the_header(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    store = FakeEvidenceStore()
    name = 'a";filename=evil.exe; x=%41.pdf'
    evidence = seed_evidence(postgres_engine, seeded, store, name=name)

    for client in client_for(postgres_engine, seeded, seeded.owner_id, store):
        response = client.get(url(evidence))

    header = response.headers["content-disposition"]
    assert header == (
        'attachment; filename="a__filename=evil.exe_ x=_41.pdf"; '
        f"filename*=UTF-8''{quote(name, safe='')}"
    )
    assert header.count('"') == 2
    assert "evil.exe;" not in header


@pytest.mark.parametrize("stored", [None, "text/html", "application/x-msdownload", "image/svg+xml"])
def test_a_content_type_outside_the_allow_list_is_served_as_octet_stream(
    postgres_engine: Engine, seeded: SeededCollaboration, stored: str | None
) -> None:
    store = FakeEvidenceStore()
    evidence = seed_evidence(
        postgres_engine, seeded, store, name="x.pdf", content_type=stored
    )

    for client in client_for(postgres_engine, seeded, seeded.owner_id, store):
        response = client.get(url(evidence))

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_no_transaction_is_open_while_the_body_is_streaming(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    observed: list[int] = []
    store = FakeEvidenceStore(
        while_streaming=lambda: observed.append(idle_in_transaction_connections(postgres_engine))
    )
    evidence = seed_evidence(postgres_engine, seeded, store, b"x" * 40)

    for client in client_for(postgres_engine, seeded, seeded.owner_id, store):
        response = client.get(url(evidence))

    assert response.status_code == 200
    assert observed == [0] * 10  # 40 bytes in chunks of 4


def test_real_cookie_authentication_leaves_no_transaction_open_while_streaming(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    """The production dependency chain: cookie, session lookup, password-change gate and the
    `touch` that runs when the request scope exits."""
    login_name = f"owner-{seeded.owner_id.hex}"
    with Session(postgres_engine) as session, session.begin():
        session.add(
            LocalCredentialRecord(
                user_id=seeded.owner_id,
                organization_id=seeded.organization_id,
                login_name=login_name,
                password_hash=PASSWORD_HASH.hash("owner-password-1"),
                password_changed_at=datetime.now(UTC),
                must_change_password=False,
            )
        )
    token, _ = _login(postgres_engine, login_name, "owner-password-1")
    observed: list[int] = []
    store = FakeEvidenceStore(
        while_streaming=lambda: observed.append(idle_in_transaction_connections(postgres_engine))
    )
    evidence = seed_evidence(postgres_engine, seeded, store, b"x" * 12)
    app = create_app()

    def database() -> Iterator[Session]:
        with Session(postgres_engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    from sqlalchemy.orm import sessionmaker

    app.dependency_overrides[get_database_session] = database
    app.dependency_overrides[get_session_factory] = lambda: sessionmaker(
        postgres_engine, expire_on_commit=False
    )
    app.dependency_overrides[downloads.get_optional_evidence_store] = lambda: store
    cookie = {"Cookie": f"{get_settings().session_cookie_name}={token}"}
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get(url(evidence), headers=cookie)
        anonymous = client.get(url(evidence))

    assert response.status_code == 200 and response.content == b"x" * 12
    assert observed == [0, 0, 0]
    assert anonymous.status_code == 401
    assert len(store.open_calls) == 1


def test_a_missing_object_is_a_500_with_a_request_id_and_an_error_log(
    postgres_engine: Engine, seeded: SeededCollaboration, caplog: pytest.LogCaptureFixture
) -> None:
    store = FakeEvidenceStore()
    evidence = seed_evidence(postgres_engine, seeded, store, put=False)

    with caplog.at_level(logging.ERROR, logger="easyaudit.app"):
        for client in client_for(postgres_engine, seeded, seeded.owner_id, store):
            response = client.get(url(evidence))

    assert response.status_code == 500
    body = response.json()
    assert body["request_id"] == response.headers["x-request-id"]
    [record] = [r for r in caplog.records if r.getMessage() == "evidence_object_missing"]
    assert record.levelno == logging.ERROR
    assert record.fields == {  # type: ignore[attr-defined]
        "evidence_id": str(evidence.id),
        "storage_key": evidence.storage_key,
    }


def test_missing_object_for_a_forbidden_user_is_still_just_404(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    """Authorization comes first: the loss is not revealed to someone who may not read it."""
    store = FakeEvidenceStore()
    evidence = seed_evidence(postgres_engine, seeded, store, put=False)

    for client in client_for(postgres_engine, seeded, seeded.unrelated_id, store):
        response = client.get(url(evidence))

    assert response.status_code == 404 and store.open_calls == []



def test_unconfigured_storage_is_a_404_for_every_refusal_and_a_503_only_once_authorized(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    evidence = seed_evidence(postgres_engine, seeded, FakeEvidenceStore())
    foreign = _seed_collaboration_shape(postgres_engine)
    for client in client_for(postgres_engine, seeded, seeded.unrelated_id, None):
        forbidden = client.get(url(evidence))
        unknown = client.get(f"/api/v1/evidences/{uuid4()}/content")
    for client in client_for(
        postgres_engine, seeded, foreign.owner_id, None, organization_id=foreign.organization_id
    ):
        cross_organization = client.get(url(evidence))
    for client in client_for(postgres_engine, seeded, seeded.owner_id, None):
        authorized = client.get(url(evidence))

    assert [r.status_code for r in (forbidden, unknown, cross_organization)] == [404, 404, 404]
    assert authorized.status_code == 503


@pytest.mark.parametrize("object_size_delta", [-1, 1])
def test_an_object_whose_size_differs_from_the_metadata_is_a_500_and_sends_no_content(
    postgres_engine: Engine,
    seeded: SeededCollaboration,
    caplog: pytest.LogCaptureFixture,
    object_size_delta: int,
) -> None:
    store = FakeEvidenceStore()
    evidence = seed_evidence(postgres_engine, seeded, store, b"x" * 20)
    store.objects[evidence.storage_key] = b"x" * (20 + object_size_delta)

    with caplog.at_level(logging.ERROR, logger="easyaudit.app"):
        for client in client_for(postgres_engine, seeded, seeded.owner_id, store):
            response = client.get(url(evidence))

    assert response.status_code == 500
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "content-disposition" not in response.headers
    assert store.streams[0].closed and store.streams[0].chunks_served == 0
    [record] = [r for r in caplog.records if r.getMessage() == "evidence_object_size_mismatch"]
    assert record.fields == {  # type: ignore[attr-defined]
        "evidence_id": str(evidence.id),
        "storage_key": evidence.storage_key,
    }
