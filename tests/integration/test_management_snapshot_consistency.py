"""Management reads see one database snapshot, even if another Session commits mid-request."""

import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, update
from sqlalchemy.orm import Session

from easyaudit_next.api.dependencies import get_current_identity, get_database_session
from easyaudit_next.main import create_app
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.review_core.persistence.models import FindingRecord, ReviewCaseRecord
from tests.integration.test_management_api import (
    NOW,
    _identity,
    _seed_process_review_api_shape,
)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _client(engine: Engine, organization_id: OrganizationId, user_id: UserId) -> TestClient:
    app = create_app()
    identity = _identity(organization_id, user_id)
    app.dependency_overrides[get_current_identity] = lambda: identity

    def database_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_database_session] = database_session
    return TestClient(app)


def _commit_concurrent_change(
    engine: Engine, case_id: UUID, organization_id: OrganizationId, caller_id: UserId
) -> None:
    """Another Session closes the Case and raises one more Finding, then commits."""
    with Session(engine) as other, other.begin():
        other.execute(
            update(ReviewCaseRecord)
            .where(ReviewCaseRecord.id == case_id)
            .values(lifecycle="closed", closed_at=NOW)
        )
        other.add(
            FindingRecord(
                id=uuid4(),
                organization_id=organization_id,
                case_id=case_id,
                title="Raised while the request was running",
                description=None,
                severity="low",
                lifecycle="open",
                raised_by=caller_id,
                raised_at=NOW,
                scenario_data_json={},
            )
        )


def _fire_once_before_findings_load(
    engine: Engine, change: Any
) -> tuple[dict[str, bool], Any]:
    """Inject `change` between the Case load and the Finding load of one projection."""
    state = {"fired": False}

    def before_cursor_execute(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        if state["fired"] or not statement.lstrip().startswith("SELECT"):
            return
        if "FROM findings" in statement and "FROM action_items" not in statement:
            state["fired"] = True
            change()

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    return state, before_cursor_execute


def test_list_review_cases_reads_one_snapshot_across_load_queries(
    postgres_engine: Engine,
) -> None:
    organization_id, caller_id, _, lead_case_id, _, _ = _seed_process_review_api_shape(
        postgres_engine
    )
    client = _client(postgres_engine, organization_id, caller_id)

    state, listener = _fire_once_before_findings_load(
        postgres_engine,
        lambda: _commit_concurrent_change(
            postgres_engine, lead_case_id, organization_id, caller_id
        ),
    )
    try:
        during = client.get("/api/v1/management/review-cases")
    finally:
        event.remove(postgres_engine, "before_cursor_execute", listener)

    assert state["fired"], "the concurrent commit must land between the two load queries"
    assert during.status_code == 200
    [item] = during.json()["items"]
    # Pre-change state: still in progress with exactly the one seeded Finding. READ COMMITTED
    # would report the old lifecycle together with the new Finding count.
    assert item["lifecycle"] == "in_progress"
    assert item["findings"]["total"] == 1

    after = client.get("/api/v1/management/review-cases").json()["items"]
    assert after[0]["lifecycle"] == "closed"
    assert after[0]["findings"]["total"] == 2
