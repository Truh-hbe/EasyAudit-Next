"""Evidence upload against real PostgreSQL, with an in-memory object store.

The upload route must authorize before storing a byte, hold no transaction while the body is
streaming, and clean the object up if registration (which re-authorizes under the Finding
lock) fails.
"""

import hashlib
import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from easyaudit_next.api import review_evidence_uploads as uploads
from easyaudit_next.api.dependencies import (
    get_current_identity,
    get_database_session,
    get_session_factory,
)
from easyaudit_next.composition import build_rectification_service
from easyaudit_next.main import create_app
from easyaudit_next.platform.persistence.models import LocalCredentialRecord, UserRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.platform.settings import get_settings
from easyaudit_next.review_core.application.evidence_policy import EvidenceUploadPolicy
from easyaudit_next.review_core.persistence.models import ActivityRecord, EvidenceRecord
from tests.evidence_support import FakeEvidenceStore
from tests.integration.test_credential_readiness import PASSWORD_HASH, _login
from tests.integration.test_review_resource_queries import (
    SeededCollaboration,
    _actor,
    _identity,
    _seed_collaboration_shape,
)

PDF = {"Content-Type": "application/pdf", "X-Evidence-Filename": "torque-record.pdf"}


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def seeded(postgres_engine: Engine) -> SeededCollaboration:
    return _seed_collaboration_shape(postgres_engine)


def upload_url(seeded: SeededCollaboration) -> str:
    return f"/api/v1/action-items/{seeded.action_id}/evidence-uploads"


def client_for(
    engine: Engine,
    seeded: SeededCollaboration,
    user_id: Any,
    store: FakeEvidenceStore,
    *,
    organization_id: Any = None,
    max_bytes: int = 1024 * 1024,
) -> Iterator[TestClient]:
    actor = _actor(user_id, organization_id or seeded.organization_id, "Uploader")
    app = create_app()

    def database() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_database_session] = database
    app.dependency_overrides[get_current_identity] = lambda: _identity(actor)
    app.dependency_overrides[get_session_factory] = lambda: sessionmaker(
        engine, expire_on_commit=False
    )
    app.dependency_overrides[uploads.get_evidence_object_store] = lambda: store
    app.dependency_overrides[uploads.get_evidence_upload_policy] = lambda: (
        EvidenceUploadPolicy.from_config(max_bytes, "application/pdf,text/plain")
    )
    with TestClient(app) as client:
        yield client


def evidence_rows(engine: Engine, seeded: SeededCollaboration) -> list[EvidenceRecord]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(EvidenceRecord).where(
                    EvidenceRecord.organization_id == seeded.organization_id,
                    EvidenceRecord.action_item_id == seeded.action_id,
                )
            )
        )


def idle_in_transaction_connections(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND state LIKE 'idle in transaction%' AND pid <> pg_backend_pid()"
                )
            ).scalar_one()
        )


def cancel_action(engine: Engine, seeded: SeededCollaboration) -> None:
    """Only an assignee may transition the Action; the owner is the one uploading."""
    with Session(engine, expire_on_commit=False) as session, session.begin():
        assignee = SqlAlchemyUserRepository(session).get(seeded.assignee_id)
        assert assignee is not None
        build_rectification_service(session).transition_action_item(
            assignee, seeded.action_id, "cancel", reason="duplicate"
        )


def test_owner_upload_registers_server_computed_metadata_and_activity(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    store = FakeEvidenceStore()
    content = b"%PDF-1.7 torque record" * 50

    for client in client_for(postgres_engine, seeded, seeded.owner_id, store):
        response = client.post(
            upload_url(seeded),
            content=content,
            headers=PDF,
            params={"description": "scanned record", "sha256": "0" * 64, "storage_key": "evil"},
        )

    assert response.status_code == 201
    body = response.json()
    [row] = evidence_rows(postgres_engine, seeded)
    assert str(row.id) == body["id"]
    assert row.storage_key == body["storage_key"] and row.storage_key != "evil"
    assert row.sha256 == hashlib.sha256(content).hexdigest()
    assert row.size_bytes == len(content)
    assert row.original_name == "torque-record.pdf" and row.content_type == "application/pdf"
    assert row.uploaded_by == seeded.owner_id
    assert store.objects == {row.storage_key: content}
    with Session(postgres_engine) as session:
        activities = session.scalars(
            select(ActivityRecord).where(
                ActivityRecord.action_item_id == seeded.action_id,
                ActivityRecord.event_type == "action_item.evidence_registered",
            )
        ).all()
    assert [a.metadata_json["sha256"] for a in activities] == [row.sha256]


def test_assignee_may_upload_too(postgres_engine: Engine, seeded: SeededCollaboration) -> None:
    store = FakeEvidenceStore()

    for client in client_for(postgres_engine, seeded, seeded.assignee_id, store):
        response = client.post(upload_url(seeded), content=b"data", headers=PDF)

    assert response.status_code == 201


def test_no_transaction_is_open_while_the_body_is_uploading(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    observed: list[tuple[str, int]] = []
    store = FakeEvidenceStore(
        while_receiving=lambda: observed.append(
            ("before body", idle_in_transaction_connections(postgres_engine))
        ),
        after_received=lambda: observed.append(
            ("after body", idle_in_transaction_connections(postgres_engine))
        ),
    )

    def body() -> Iterator[bytes]:
        for _ in range(4):
            yield b"x" * 1000

    for client in client_for(postgres_engine, seeded, seeded.owner_id, store):
        response = client.post(upload_url(seeded), content=body(), headers=PDF)

    assert response.status_code == 201
    assert observed == [("before body", 0), ("after body", 0)]


def test_real_session_authentication_leaves_no_transaction_open_while_streaming(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    """The same check through the production dependency chain: cookie, session lookup,
    password-change gate and the `touch` that runs when the request scope exits."""
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
        while_receiving=lambda: observed.append(idle_in_transaction_connections(postgres_engine)),
        after_received=lambda: observed.append(idle_in_transaction_connections(postgres_engine)),
    )
    app = create_app()

    def database() -> Iterator[Session]:
        with Session(postgres_engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    app.dependency_overrides[get_database_session] = database
    app.dependency_overrides[get_session_factory] = lambda: sessionmaker(
        postgres_engine, expire_on_commit=False
    )
    app.dependency_overrides[uploads.get_evidence_object_store] = lambda: store
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post(
            upload_url(seeded),
            content=b"data",
            headers={**PDF, "Cookie": f"{get_settings().session_cookie_name}={token}"},
        )
        unauthenticated = client.post(upload_url(seeded), content=b"data", headers=PDF)

    assert response.status_code == 201, response.text
    assert observed == [0, 0]
    assert unauthenticated.status_code == 401
    assert len(store.put_calls) == 1  # the unauthenticated request stored nothing


def test_the_open_transaction_probe_is_not_vacuous(postgres_engine: Engine) -> None:
    with postgres_engine.connect() as connection:
        connection.execute(text("SELECT 1"))  # autobegin: the connection is now idle in tx
        assert idle_in_transaction_connections(postgres_engine) >= 1


def test_unauthorized_user_is_refused_before_any_byte_is_stored(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    store = FakeEvidenceStore()

    for client in client_for(postgres_engine, seeded, seeded.unrelated_id, store):
        unrelated = client.post(upload_url(seeded), content=b"data", headers=PDF)
    for client in client_for(postgres_engine, seeded, seeded.admin_id, store):
        admin = client.post(upload_url(seeded), content=b"data", headers=PDF)

    assert unrelated.status_code == 403 and admin.status_code == 403
    assert store.put_calls == [] and store.objects == {}
    assert evidence_rows(postgres_engine, seeded) == []


def test_other_organizations_user_gets_404_and_nothing_is_stored(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    foreign = _seed_collaboration_shape(postgres_engine)
    store = FakeEvidenceStore()

    for client in client_for(
        postgres_engine, seeded, foreign.owner_id, store, organization_id=foreign.organization_id
    ):
        response = client.post(upload_url(seeded), content=b"data", headers=PDF)

    assert response.status_code == 404
    assert store.put_calls == [] and store.objects == {}
    assert evidence_rows(postgres_engine, seeded) == []


def test_action_cancelled_during_the_upload_deletes_the_object_and_returns_422(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    store = FakeEvidenceStore(after_received=lambda: cancel_action(postgres_engine, seeded))

    for client in client_for(postgres_engine, seeded, seeded.owner_id, store):
        response = client.post(upload_url(seeded), content=b"data", headers=PDF)

    assert response.status_code == 422
    assert "cancelled" in response.json()["detail"]
    assert store.objects == {} and len(store.deleted) == 1
    assert evidence_rows(postgres_engine, seeded) == []


def test_user_deactivated_during_the_upload_is_refused_at_registration(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    def deactivate() -> None:
        with Session(postgres_engine) as session, session.begin():
            session.execute(
                update(UserRecord).where(UserRecord.id == seeded.owner_id).values(is_active=False)
            )

    store = FakeEvidenceStore(after_received=deactivate)

    for client in client_for(postgres_engine, seeded, seeded.owner_id, store):
        response = client.post(upload_url(seeded), content=b"data", headers=PDF)

    assert response.status_code == 403
    assert store.objects == {} and evidence_rows(postgres_engine, seeded) == []


def test_failed_cleanup_leaves_an_orphan_logged_by_key_only(
    postgres_engine: Engine, seeded: SeededCollaboration, caplog: pytest.LogCaptureFixture
) -> None:
    store = FakeEvidenceStore(
        after_received=lambda: cancel_action(postgres_engine, seeded), fail_delete=True
    )

    with caplog.at_level(logging.WARNING, logger="easyaudit.app"):
        for client in client_for(postgres_engine, seeded, seeded.owner_id, store):
            response = client.post(upload_url(seeded), content=b"data", headers=PDF)

    assert response.status_code == 422  # the original error, not the cleanup failure
    [key] = store.objects  # the orphan
    [record] = [r for r in caplog.records if r.getMessage() == "evidence_object_orphaned"]
    assert record.fields == {"storage_key": key}  # type: ignore[attr-defined]
    assert "torque-record" not in key
    assert evidence_rows(postgres_engine, seeded) == []


def test_oversized_upload_writes_no_metadata_and_no_object(
    postgres_engine: Engine, seeded: SeededCollaboration
) -> None:
    store = FakeEvidenceStore()

    def body() -> Iterator[bytes]:
        for _ in range(10):
            yield b"x" * 300

    for client in client_for(postgres_engine, seeded, seeded.owner_id, store, max_bytes=1000):
        streamed = client.post(upload_url(seeded), content=body(), headers=PDF)
        declared = client.post(upload_url(seeded), content=b"x" * 1001, headers=PDF)

    assert streamed.status_code == 413 and declared.status_code == 413
    assert store.objects == {}
    assert evidence_rows(postgres_engine, seeded) == []
    with Session(postgres_engine) as session:
        assert session.scalar(select(func.count()).select_from(EvidenceRecord).where(
            EvidenceRecord.organization_id == seeded.organization_id
        )) == 0


def test_request_cancelled_while_registering_keeps_metadata_and_object_together(
    postgres_engine: Engine, seeded: SeededCollaboration, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import threading

    import httpx

    started, release = threading.Event(), threading.Event()
    real_register = uploads._register

    def gated_register(*args: Any) -> Any:
        started.set()
        assert release.wait(10)
        return real_register(*args)  # the worker thread cannot be stopped: it commits

    monkeypatch.setattr(uploads, "_register", gated_register)
    store = FakeEvidenceStore()

    async def scenario(app: Any) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            request = asyncio.ensure_future(
                http.post(upload_url(seeded), content=b"data", headers=PDF)
            )
            await asyncio.to_thread(started.wait, 10)
            request.cancel()
            await asyncio.sleep(0.1)
            release.set()
            await asyncio.gather(request, return_exceptions=True)
            await asyncio.sleep(0.5)  # let the shielded registration settle

    for client in client_for(postgres_engine, seeded, seeded.owner_id, store):
        asyncio.run(scenario(client.app))

    rows = evidence_rows(postgres_engine, seeded)
    assert len(rows) == 1  # it committed, so the object must still be there
    assert list(store.objects) == [rows[0].storage_key] and store.deleted == []
