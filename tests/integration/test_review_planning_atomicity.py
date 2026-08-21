import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.persistence.models import OrganizationRecord, UserRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.review_planning import (
    ReviewAuthorizationError,
    ReviewPlanningService,
)
from easyaudit_next.review_core.domain.ids import ReviewCaseId
from easyaudit_next.review_core.domain.models import ScenarioKey, ScenarioVersion
from easyaudit_next.review_core.persistence.models import (
    ActivityRecord,
    CaseMemberRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)
from easyaudit_next.review_core.persistence.repositories import (
    SqlAlchemyReviewCoreRepository,
    SqlAlchemyScenarioCatalogRepository,
)

NOW = datetime(2026, 8, 21, 9, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_process_review(
    engine: Engine,
    *,
    second_same_org_user: bool = False,
) -> tuple[OrganizationId, UserId, UserId | None]:
    organization_id = OrganizationId(uuid4())
    creator_id = UserId(uuid4())
    second_user_id = UserId(uuid4()) if second_same_org_user else None
    scenario_id = uuid4()
    version_id = uuid4()
    with Session(engine) as session, session.begin():
        session.add(OrganizationRecord(id=organization_id, name=f"M2.2 {organization_id}"))
        session.flush()
        users = [
            UserRecord(
                id=creator_id,
                organization_id=organization_id,
                display_name="Case Creator",
                platform_role="ordinary_user",
            )
        ]
        if second_user_id is not None:
            users.append(
                UserRecord(
                    id=second_user_id,
                    organization_id=organization_id,
                    display_name="Other User",
                    platform_role="ordinary_user",
                )
            )
        session.add_all(users)
        session.flush()
        session.add(
            ScenarioRecord(
                id=scenario_id,
                organization_id=organization_id,
                key="process_review",
                name="Process Review",
            )
        )
        session.flush()
        session.add(
            ScenarioVersionRecord(
                id=version_id,
                scenario_id=scenario_id,
                organization_id=organization_id,
                version=1,
                published_at=NOW,
            )
        )
    return organization_id, creator_id, second_user_id


def _service(
    session: Session,
    repository: SqlAlchemyReviewCoreRepository | None = None,
) -> ReviewPlanningService:
    return ReviewPlanningService(
        repository or SqlAlchemyReviewCoreRepository(session),
        SqlAlchemyScenarioCatalogRepository(session),
        SqlAlchemyUserRepository(session),
        build_scenario_registry(),
    )


def test_m2_2_migration_adds_case_planning_and_scenario_data_columns(
    postgres_engine: Engine,
) -> None:
    names = {column["name"] for column in inspect(postgres_engine).get_columns("review_cases")}
    assert {
        "planned_start_at",
        "planned_end_at",
        "started_at",
        "fieldwork_completed_at",
        "closed_at",
        "scenario_data",
    } <= names


def test_case_creation_commits_case_initial_lead_and_created_activity_together(
    postgres_engine: Engine,
) -> None:
    organization_id, creator_id, _ = _seed_process_review(postgres_engine)
    title = f"Atomic success {uuid4()}"

    with Session(postgres_engine, expire_on_commit=False) as session:
        creator = SqlAlchemyUserRepository(session).get(creator_id)
        assert creator is not None
        review_case = _service(session).create_case(
            creator,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            title,
            {"area_code": "ASSY", "review_type": "routine"},
            occurred_at=NOW,
        )
        case_id = review_case.id
        session.commit()

    with Session(postgres_engine) as verification:
        case_record = verification.scalar(
            select(ReviewCaseRecord).where(
                ReviewCaseRecord.organization_id == organization_id,
                ReviewCaseRecord.id == case_id,
            )
        )
        lead = verification.scalar(
            select(CaseMemberRecord).where(
                CaseMemberRecord.organization_id == organization_id,
                CaseMemberRecord.case_id == case_id,
                CaseMemberRecord.user_id == creator_id,
                CaseMemberRecord.role_key == "lead",
            )
        )
        activity = verification.scalar(
            select(ActivityRecord).where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.review_case_id == case_id,
                ActivityRecord.event_type == "review_case.created",
                ActivityRecord.actor_id == creator_id,
            )
        )
        assert case_record is not None
        assert case_record.lifecycle == "draft"
        assert case_record.scenario_data_json == {
            "area_code": "ASSY",
            "review_type": "routine",
        }
        assert lead is not None
        assert activity is not None


class _RejectCreatedActivityRepository(SqlAlchemyReviewCoreRepository):
    """Make the third atomic write fail through a real PostgreSQL CHECK constraint."""

    def add_activity(self, activity: object) -> None:
        # Case and CaseMember have already been flushed when this executes. An empty event_type
        # violates ck_activities_event_type, forcing the surrounding database transaction to fail.
        assert hasattr(activity, "organization_id")
        assert hasattr(activity, "subject")
        subject = activity.subject  # type: ignore[attr-defined]
        self._session.add(  # type: ignore[attr-defined]
            ActivityRecord(
                id=uuid4(),
                organization_id=activity.organization_id,  # type: ignore[attr-defined]
                actor_id=activity.actor_id,  # type: ignore[attr-defined]
                event_type="",
                occurred_at=NOW,
                review_case_id=subject.review_case_id,  # type: ignore[attr-defined]
                metadata_json={},
            )
        )
        self._session.flush()  # type: ignore[attr-defined]


def test_case_creation_rolls_back_case_and_lead_when_activity_insert_fails(
    postgres_engine: Engine,
) -> None:
    organization_id, creator_id, _ = _seed_process_review(postgres_engine)
    title = f"Atomic rollback {uuid4()}"

    with pytest.raises(IntegrityError):
        with Session(postgres_engine) as session, session.begin():
            creator = SqlAlchemyUserRepository(session).get(creator_id)
            assert creator is not None
            repository = _RejectCreatedActivityRepository(session)
            _service(session, repository).create_case(
                creator,
                ScenarioKey("process_review"),
                ScenarioVersion(1),
                title,
                {"area_code": "ASSY", "review_type": "routine"},
                occurred_at=NOW,
            )

    with Session(postgres_engine) as verification:
        case_count = verification.scalar(
            select(func.count())
            .select_from(ReviewCaseRecord)
            .where(
                ReviewCaseRecord.organization_id == organization_id,
                ReviewCaseRecord.title == title,
            )
        )
        member_count = verification.scalar(
            select(func.count())
            .select_from(CaseMemberRecord)
            .join(
                ReviewCaseRecord,
                (ReviewCaseRecord.id == CaseMemberRecord.case_id)
                & (ReviewCaseRecord.organization_id == CaseMemberRecord.organization_id),
            )
            .where(
                CaseMemberRecord.organization_id == organization_id,
                ReviewCaseRecord.title == title,
            )
        )
        activity_count = verification.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .join(
                ReviewCaseRecord,
                (ReviewCaseRecord.id == ActivityRecord.review_case_id)
                & (ReviewCaseRecord.organization_id == ActivityRecord.organization_id),
            )
            .where(
                ActivityRecord.organization_id == organization_id,
                ReviewCaseRecord.title == title,
            )
        )
        assert case_count == 0
        assert member_count == 0
        assert activity_count == 0


def test_case_reads_are_organization_scoped_and_role_authorized(
    postgres_engine: Engine,
) -> None:
    organization_id, creator_id, other_user_id = _seed_process_review(
        postgres_engine,
        second_same_org_user=True,
    )
    assert other_user_id is not None

    with Session(postgres_engine, expire_on_commit=False) as session:
        users = SqlAlchemyUserRepository(session)
        creator = users.get(creator_id)
        other = users.get(other_user_id)
        assert creator is not None and other is not None
        service = _service(session)
        review_case = service.create_case(
            creator,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            f"Authorization {uuid4()}",
            {"area_code": "ASSY", "review_type": "routine"},
            occurred_at=NOW,
        )
        case_id = ReviewCaseId(review_case.id)
        with pytest.raises(ReviewAuthorizationError):
            service.get_case(other, case_id)
        session.commit()

    foreign_organization_id, foreign_user_id, _ = _seed_process_review(postgres_engine)
    with Session(postgres_engine) as session:
        foreign_user = SqlAlchemyUserRepository(session).get(foreign_user_id)
        assert foreign_user is not None
        repository = SqlAlchemyReviewCoreRepository(session)
        assert repository.get_case(foreign_organization_id, case_id) is None


def test_lead_can_drive_m2_2_case_through_fieldwork_completion(
    postgres_engine: Engine,
) -> None:
    _, creator_id, _ = _seed_process_review(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as session:
        creator = SqlAlchemyUserRepository(session).get(creator_id)
        assert creator is not None
        service = _service(session)
        review_case = service.create_case(
            creator,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            f"Transition {uuid4()}",
            {"area_code": "ASSY", "review_type": "routine"},
            occurred_at=NOW,
        )
        scheduled = service.transition_case(creator, review_case.id, "schedule", occurred_at=NOW)
        started = service.transition_case(creator, review_case.id, "start", occurred_at=NOW)
        awaiting = service.transition_case(
            creator,
            review_case.id,
            "finish_fieldwork",
            occurred_at=NOW,
        )
        assert scheduled.lifecycle.value == "scheduled"
        assert started.lifecycle.value == "in_progress"
        assert started.started_at == NOW
        assert awaiting.lifecycle.value == "awaiting_closure"
        assert awaiting.fieldwork_completed_at == NOW
        session.commit()
