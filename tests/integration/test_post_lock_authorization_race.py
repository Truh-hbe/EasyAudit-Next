"""Double-Session races: a Case role revoked while a write waits for the Case lock.

Session A (V, a lead) removes a Case role of U and holds the Case lock uncommitted.
Session B (U) passes every pre-lock check on the still-committed membership, then waits.
Once A commits, B must authorize against the post-lock membership and be refused.
"""

import os
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_case_team_coordinator,
    build_finding_lifecycle_service,
    build_manual_nudge_service,
    build_review_planning_service,
    build_verification_closure_service,
)
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.domain.models import User
from easyaudit_next.platform.persistence.models import OrganizationRecord, UserRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.review_planning import ReviewAuthorizationError
from easyaudit_next.review_core.domain.ids import FindingId, ReviewCaseId
from easyaudit_next.review_core.domain.models import FindingSeverity, UserActor
from easyaudit_next.review_core.persistence.models import (
    ActivityRecord,
    CaseMemberRecord,
    FindingParticipantRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)

NOW = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


class Seed:
    def __init__(self, engine: Engine, case_lifecycle: str, finding_lifecycle: str | None):
        self.engine = engine
        self.organization_id = OrganizationId(uuid4())
        self.lead_u, self.lead_v, self.reviewer, self.observer, self.candidate = (
            UserId(uuid4()) for _ in range(5)
        )
        self.case_id = uuid4()
        self.finding_id = uuid4() if finding_lifecycle is not None else None
        scenario_id, version_id = uuid4(), uuid4()
        org = self.organization_id
        with Session(engine) as session, session.begin():
            session.add(OrganizationRecord(id=org, name=f"B2 {org}"))
            session.add_all(
                UserRecord(
                    id=user_id,
                    organization_id=org,
                    display_name=name,
                    platform_role="ordinary_user",
                )
                for user_id, name in (
                    (self.lead_u, "Lead U"),
                    (self.lead_v, "Lead V"),
                    (self.reviewer, "Reviewer"),
                    (self.observer, "Observer"),
                    (self.candidate, "Candidate"),
                )
            )
            session.flush()
            session.add(
                ScenarioRecord(
                    id=scenario_id, organization_id=org, key="process_review", name="PR"
                )
            )
            session.flush()
            session.add(
                ScenarioVersionRecord(
                    id=version_id,
                    scenario_id=scenario_id,
                    organization_id=org,
                    version=1,
                    published_at=NOW,
                )
            )
            session.flush()
            session.add(
                ReviewCaseRecord(
                    id=self.case_id,
                    organization_id=org,
                    plan_id=None,
                    scenario_version_id=version_id,
                    title="Post-lock authorization",
                    lifecycle=case_lifecycle,
                    planned_start_at=None,
                    planned_end_at=None,
                    started_at=None if case_lifecycle == "draft" else NOW,
                    fieldwork_completed_at=None,
                    closed_at=None,
                    scenario_data_json={"area_code": "ASSY", "review_type": "routine"},
                    created_by=self.lead_u,
                    created_at=NOW,
                )
            )
            session.flush()
            session.add_all(
                CaseMemberRecord(
                    organization_id=org,
                    case_id=self.case_id,
                    user_id=user_id,
                    role_key=role,
                    joined_at=NOW,
                )
                for user_id, role in (
                    (self.lead_u, "lead"),
                    (self.lead_v, "lead"),
                    (self.reviewer, "reviewer"),
                    (self.observer, "observer"),
                )
            )
            if self.finding_id is not None:
                assert finding_lifecycle is not None
                session.add(
                    FindingRecord(
                        id=self.finding_id,
                        organization_id=org,
                        case_id=self.case_id,
                        title="Seed finding",
                        description=None,
                        severity="high",
                        lifecycle=finding_lifecycle,
                        raised_by=self.lead_u,
                        raised_at=NOW,
                        scenario_data_json={
                            "issue_type": "control_gap",
                            "project_category": "assembly",
                        },
                    )
                )

    def count(self, model: Any, *criteria: Any) -> int:
        with Session(self.engine) as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.organization_id == self.organization_id, *criteria)
                )
                or 0
            )

    def activities(self, event_type: str) -> int:
        return self.count(ActivityRecord, ActivityRecord.event_type == event_type)


def _someone_waits_on_a_lock(engine: Engine) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
        )


def _run_race(
    seed: Seed,
    revoke: Callable[[Session, User], None],
    stale_write: Callable[[Session, User], object],
    stale_user: UserId,
) -> BaseException | None:
    def session_b() -> None:
        with Session(seed.engine) as session, session.begin():
            user = SqlAlchemyUserRepository(session).get(stale_user)
            assert user is not None
            stale_write(session, user)

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        session_a = Session(seed.engine)
        transaction = session_a.begin()
        lead = SqlAlchemyUserRepository(session_a).get(seed.lead_v)
        assert lead is not None
        revoke(session_a, lead)
        future = pool.submit(session_b)
        deadline = time.monotonic() + 10
        while not future.done() and time.monotonic() < deadline:
            if _someone_waits_on_a_lock(seed.engine):
                break
            time.sleep(0.05)
        transaction.commit()
        session_a.close()
        return future.exception(timeout=15)
    finally:
        pool.shutdown(wait=True)


def _remove_member(seed: Seed, user_id: UserId, role_key: str) -> Callable[[Session, User], None]:
    def revoke(session: Session, actor: User) -> None:
        build_case_team_coordinator(session).remove_case_member_result(
            actor,
            ReviewCaseId(seed.case_id),
            user_id,
            role_key,
            occurred_at=NOW,
        )

    return revoke


def _assert_refused(error: BaseException | None) -> None:
    assert isinstance(error, ReviewAuthorizationError), repr(error)


def test_revoked_lead_cannot_add_case_member(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine, "in_progress", None)

    def write(session: Session, user: User) -> object:
        return build_case_team_coordinator(session).add_case_member_result(
            user,
            ReviewCaseId(seed.case_id),
            seed.candidate,
            "auditor",
            occurred_at=NOW,
        )

    error = _run_race(seed, _remove_member(seed, seed.lead_u, "lead"), write, seed.lead_u)

    _assert_refused(error)
    assert seed.activities("review_case.member_added") == 0


def test_revoked_lead_cannot_transition_case(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine, "draft", None)

    def write(session: Session, user: User) -> object:
        return build_review_planning_service(session).transition_case(
            user, ReviewCaseId(seed.case_id), "schedule", occurred_at=NOW
        )

    error = _run_race(seed, _remove_member(seed, seed.lead_u, "lead"), write, seed.lead_u)

    _assert_refused(error)
    assert seed.activities("review_case.transitioned") == 0
    with Session(postgres_engine) as session:
        assert (
            session.scalar(
                select(ReviewCaseRecord.lifecycle).where(ReviewCaseRecord.id == seed.case_id)
            )
            == "draft"
        )


def test_revoked_lead_cannot_create_finding(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine, "in_progress", None)

    def write(session: Session, user: User) -> object:
        return build_finding_lifecycle_service(session).create_finding(
            user,
            ReviewCaseId(seed.case_id),
            "Stale lead finding",
            FindingSeverity.HIGH,
            {"issue_type": "control_gap", "project_category": "assembly"},
            occurred_at=NOW,
        )

    error = _run_race(seed, _remove_member(seed, seed.lead_u, "lead"), write, seed.lead_u)

    _assert_refused(error)
    assert seed.count(FindingRecord) == 0
    assert seed.activities("finding.created") == 0


def test_revoked_lead_cannot_add_finding_participant(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine, "in_progress", "open")
    assert seed.finding_id is not None

    def write(session: Session, user: User) -> object:
        return build_finding_lifecycle_service(session).add_participant_result(
            user,
            FindingId(seed.finding_id),  # type: ignore[arg-type]
            UserActor(seed.candidate),
            "owner",
            occurred_at=NOW,
        )

    error = _run_race(seed, _remove_member(seed, seed.lead_u, "lead"), write, seed.lead_u)

    _assert_refused(error)
    assert seed.count(FindingParticipantRecord) == 0
    assert seed.activities("finding.participant_added") == 0


def test_revoked_reviewer_cannot_verify_finding(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine, "in_progress", "verifying")

    def write(session: Session, user: User) -> object:
        return build_verification_closure_service(session).submit_verification(
            user,
            FindingId(seed.finding_id),  # type: ignore[arg-type]
            "approve",
            {"result": "approved"},
            occurred_at=NOW,
        )

    error = _run_race(seed, _remove_member(seed, seed.reviewer, "reviewer"), write, seed.reviewer)

    _assert_refused(error)
    assert seed.activities("finding.approved") == 0
    with Session(postgres_engine) as session:
        assert (
            session.scalar(
                select(FindingRecord.lifecycle).where(FindingRecord.id == seed.finding_id)
            )
            == "verifying"
        )


def test_unrelated_member_removal_does_not_block_valid_write(postgres_engine: Engine) -> None:
    """Control: the post-lock check passes when U's own role is untouched."""
    seed = Seed(postgres_engine, "in_progress", None)

    def write(session: Session, user: User) -> object:
        return build_finding_lifecycle_service(session).create_finding(
            user,
            ReviewCaseId(seed.case_id),
            "Valid lead finding",
            FindingSeverity.HIGH,
            {"issue_type": "control_gap", "project_category": "assembly"},
            occurred_at=NOW,
        )

    error = _run_race(
        seed, _remove_member(seed, seed.observer, "observer"), write, seed.lead_u
    )

    assert error is None
    assert seed.count(FindingRecord) == 1
    assert seed.activities("finding.created") == 1


def test_unrelated_member_removal_does_not_block_valid_transition(
    postgres_engine: Engine,
) -> None:
    seed = Seed(postgres_engine, "draft", None)

    def write(session: Session, user: User) -> object:
        return build_review_planning_service(session).transition_case(
            user, ReviewCaseId(seed.case_id), "schedule", occurred_at=NOW
        )

    error = _run_race(
        seed, _remove_member(seed, seed.observer, "observer"), write, seed.lead_u
    )

    assert error is None
    assert seed.activities("review_case.transitioned") == 1



def test_revoked_lead_cannot_nudge_finding(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine, "in_progress", "rectifying")
    with Session(postgres_engine) as session, session.begin():
        session.add(
            FindingParticipantRecord(
                id=uuid4(),
                organization_id=seed.organization_id,
                finding_id=seed.finding_id,
                user_id=seed.candidate,
                role_key="owner",
                assigned_at=NOW,
            )
        )

    def write(session: Session, user: User) -> object:
        return build_manual_nudge_service(session).nudge_finding(
            user, seed.finding_id, occurred_at=NOW  # type: ignore[arg-type]
        )

    error = _run_race(seed, _remove_member(seed, seed.lead_u, "lead"), write, seed.lead_u)

    assert isinstance(error, LookupError), repr(error)
    assert seed.activities("finding.nudged") == 0
