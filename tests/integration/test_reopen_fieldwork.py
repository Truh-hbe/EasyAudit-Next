"""reopen_fieldwork: awaiting_closure -> in_progress with a required reason (real PostgreSQL)."""

import os
from collections.abc import Callable, Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from easyaudit_next.api.dependencies import (
    CurrentIdentity,
    get_database_session,
    require_business_identity,
)
from easyaudit_next.composition import (
    build_finding_lifecycle_service,
    build_review_planning_service,
)
from easyaudit_next.main import create_app
from easyaudit_next.platform.domain.ids import AuthSessionId
from easyaudit_next.platform.domain.models import AuthSession, User
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.authorization import (
    ConcurrentCaseTransitionError,
    ReviewAuthorizationError,
)
from easyaudit_next.review_core.domain.ids import ReviewCaseId
from easyaudit_next.review_core.domain.models import FindingSeverity
from easyaudit_next.review_core.domain.scenario_capabilities import WorkflowTransitionError
from easyaudit_next.review_core.persistence.models import (
    ActivityRecord,
    FindingRecord,
    ReviewCaseRecord,
)
from tests.integration.test_post_lock_authorization_race import NOW, Seed, _run_race


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _transition(
    seed: Seed, action: str, reason: str | None = None
) -> Callable[[Session, User], object]:
    def run(session: Session, user: User) -> object:
        return build_review_planning_service(session).transition_case(
            user, ReviewCaseId(seed.case_id), action, reason=reason, occurred_at=NOW
        )

    return run


def _case(engine: Engine, seed: Seed) -> ReviewCaseRecord:
    with Session(engine) as session:
        record = session.get(ReviewCaseRecord, seed.case_id)
        assert record is not None
        session.expunge(record)
        return record


def _as(engine: Engine, user_id: object, fn: Callable[[Session, User], object]) -> None:
    with Session(engine) as session, session.begin():
        user = SqlAlchemyUserRepository(session).get(user_id)  # type: ignore[arg-type]
        assert user is not None
        fn(session, user)


def test_reopen_fieldwork_restores_in_progress_and_allows_findings_again(
    postgres_engine: Engine,
) -> None:
    seed = Seed(postgres_engine, "in_progress", None)
    _as(postgres_engine, seed.lead_u, _transition(seed, "finish_fieldwork"))
    finished = _case(postgres_engine, seed)
    assert finished.lifecycle == "awaiting_closure"
    assert finished.fieldwork_completed_at is not None

    _as(postgres_engine, seed.lead_u, _transition(seed, "reopen_fieldwork", "补录发现项"))
    reopened = _case(postgres_engine, seed)
    assert reopened.lifecycle == "in_progress"
    assert reopened.fieldwork_completed_at is None  # 现场工作尚未再次完成
    assert reopened.started_at == finished.started_at  # 首次开始时间不变

    with Session(postgres_engine) as session:
        activities = session.scalars(
            select(ActivityRecord)
            .where(
                ActivityRecord.organization_id == seed.organization_id,
                ActivityRecord.event_type == "review_case.transitioned",
            )
            .order_by(ActivityRecord.occurred_at, ActivityRecord.id)
        ).all()
    reopen = [a for a in activities if a.metadata_json.get("action") == "reopen_fieldwork"]
    assert len(reopen) == 1
    assert reopen[0].metadata_json == {
        "action": "reopen_fieldwork",
        "from_lifecycle": "awaiting_closure",
        "to_lifecycle": "in_progress",
        "reason": "补录发现项",
    }

    def create(session: Session, user: User) -> object:
        return build_finding_lifecycle_service(session).create_finding(
            user,
            ReviewCaseId(seed.case_id),
            "Found after reopening",
            FindingSeverity.HIGH,
            {"issue_type": "control_gap", "project_category": "assembly"},
            occurred_at=NOW,
        )

    _as(postgres_engine, seed.lead_u, create)
    assert seed.count(FindingRecord) == 1

    # 再次完成现场工作会重新记录完成时间，而不是沿用旧值。
    _as(postgres_engine, seed.lead_u, _transition(seed, "finish_fieldwork"))
    assert _case(postgres_engine, seed).fieldwork_completed_at is not None


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_reopen_fieldwork_requires_a_reason_and_writes_nothing_on_rejection(
    postgres_engine: Engine, reason: str | None
) -> None:
    seed = Seed(postgres_engine, "awaiting_closure", None)

    with pytest.raises(WorkflowTransitionError, match="requires a reason"):
        _as(postgres_engine, seed.lead_u, _transition(seed, "reopen_fieldwork", reason))

    assert _case(postgres_engine, seed).lifecycle == "awaiting_closure"
    assert seed.activities("review_case.transitioned") == 0


def test_reopen_fieldwork_needs_the_same_role_as_finish_fieldwork(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine, "awaiting_closure", None)
    for user_id in (seed.reviewer, seed.observer, seed.candidate):
        with pytest.raises(ReviewAuthorizationError):
            _as(postgres_engine, user_id, _transition(seed, "reopen_fieldwork", "x"))
    assert _case(postgres_engine, seed).lifecycle == "awaiting_closure"
    assert seed.activities("review_case.transitioned") == 0


@pytest.mark.parametrize("lifecycle", ["draft", "scheduled", "in_progress", "closed", "cancelled"])
def test_reopen_fieldwork_is_only_valid_from_awaiting_closure(
    postgres_engine: Engine, lifecycle: str
) -> None:
    seed = Seed(postgres_engine, lifecycle, None)
    with pytest.raises(WorkflowTransitionError):
        _as(postgres_engine, seed.lead_u, _transition(seed, "reopen_fieldwork", "x"))
    assert _case(postgres_engine, seed).lifecycle == lifecycle


def test_close_waiting_on_reopen_fieldwork_is_a_409(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine, "awaiting_closure", None)

    error = _run_race(
        seed,
        lambda session, lead: _transition(seed, "reopen_fieldwork", "补录")(session, lead),
        _transition(seed, "close"),
        seed.lead_u,
    )

    assert isinstance(error, ConcurrentCaseTransitionError), repr(error)
    assert _case(postgres_engine, seed).lifecycle == "in_progress"
    assert seed.activities("review_case.transitioned") == 1


def test_reopen_fieldwork_waiting_on_close_is_a_409(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine, "awaiting_closure", None)

    error = _run_race(
        seed,
        lambda session, lead: _transition(seed, "close")(session, lead),
        _transition(seed, "reopen_fieldwork", "补录"),
        seed.lead_u,
    )

    assert isinstance(error, ConcurrentCaseTransitionError), repr(error)
    assert _case(postgres_engine, seed).lifecycle == "closed"
    assert seed.activities("review_case.transitioned") == 1


def _post_transition(
    engine: Engine, seed: Seed, user_id: object, action: str, reason: str | None
) -> Response:
    with Session(engine) as lookup:
        user = SqlAlchemyUserRepository(lookup).get(user_id)  # type: ignore[arg-type]
        assert user is not None
    identity = CurrentIdentity(
        auth_session=AuthSession(
            id=AuthSessionId(uuid4()),
            organization_id=seed.organization_id,
            user_id=user.id,
            token_hash="0" * 64,
            expires_at=NOW + timedelta(hours=1),
            created_at=NOW,
        ),
        user=user,
    )
    app = create_app()

    def database_session() -> Iterator[Session]:
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    app.dependency_overrides[get_database_session] = database_session
    app.dependency_overrides[require_business_identity] = lambda: identity
    with TestClient(app, base_url="https://testserver") as client:
        return client.post(
            f"/api/v1/review-cases/{seed.case_id}/transitions",
            json={"action": action, "reason": reason},
        )


def test_api_reopen_fieldwork_status_codes(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine, "awaiting_closure", None)

    assert (
        _post_transition(postgres_engine, seed, seed.lead_u, "reopen_fieldwork", None).status_code
        == 422
    )
    assert (
        _post_transition(postgres_engine, seed, seed.reviewer, "reopen_fieldwork", "x").status_code
        == 403
    )
    assert _case(postgres_engine, seed).lifecycle == "awaiting_closure"

    response = _post_transition(postgres_engine, seed, seed.lead_u, "reopen_fieldwork", "补录")
    assert response.status_code == 200
    assert response.json()["lifecycle"] == "in_progress"
    assert response.json()["fieldwork_completed_at"] is None

    # 已不在 awaiting_closure：再次恢复是无效流转，而不是静默成功。
    assert (
        _post_transition(
            postgres_engine, seed, seed.lead_u, "reopen_fieldwork", "again"
        ).status_code
        == 422
    )
