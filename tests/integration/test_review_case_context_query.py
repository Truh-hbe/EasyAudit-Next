import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_review_case_context_query_service
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.domain.models import PlatformRole, User
from easyaudit_next.platform.persistence.models import OrganizationRecord, UserRecord
from easyaudit_next.review_core.application.review_planning import ReviewAuthorizationError
from easyaudit_next.review_core.domain.ids import ReviewCaseId
from easyaudit_next.review_core.persistence.models import (
    ActionItemRecord,
    ActivityRecord,
    CaseMemberRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
    SubmissionRecord,
)

NOW = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _user(
    user_id: UserId,
    organization_id: OrganizationId,
    display_name: str,
) -> UserRecord:
    return UserRecord(
        id=user_id,
        organization_id=organization_id,
        display_name=display_name,
        platform_role="ordinary_user",
    )


def _actor(user_id: UserId, organization_id: OrganizationId, name: str) -> User:
    return User(
        id=user_id,
        organization_id=organization_id,
        display_name=name,
        platform_role=PlatformRole.ORDINARY_USER,
        primary_department_id=None,
    )


def _seed_case(
    session: Session,
) -> tuple[OrganizationId, UserId, UserId, UserId, ReviewCaseRecord]:
    organization_id = OrganizationId(uuid4())
    viewer_id = UserId(uuid4())
    member_id = UserId(uuid4())
    unrelated_id = UserId(uuid4())
    session.add(OrganizationRecord(id=organization_id, name=f"Context {organization_id}"))
    session.flush()
    session.add_all(
        [
            _user(viewer_id, organization_id, "Visible Viewer"),
            _user(member_id, organization_id, "Case Member Name"),
            _user(unrelated_id, organization_id, "Unrelated User"),
        ]
    )
    session.flush()

    scenario_id = uuid4()
    version_id = uuid4()
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
    session.flush()

    review_case = ReviewCaseRecord(
        id=uuid4(),
        organization_id=organization_id,
        plan_id=None,
        scenario_version_id=version_id,
        title="Context Case",
        lifecycle="in_progress",
        planned_start_at=None,
        planned_end_at=None,
        started_at=NOW,
        fieldwork_completed_at=None,
        closed_at=None,
        scenario_data_json={"area_code": "A-01", "review_type": "routine"},
        created_by=viewer_id,
        created_at=NOW,
    )
    session.add(review_case)
    session.flush()
    session.add_all(
        [
            CaseMemberRecord(
                organization_id=organization_id,
                case_id=review_case.id,
                user_id=viewer_id,
                role_key="lead",
                joined_at=NOW,
            ),
            CaseMemberRecord(
                organization_id=organization_id,
                case_id=review_case.id,
                user_id=member_id,
                role_key="observer",
                joined_at=NOW + timedelta(seconds=1),
            ),
        ]
    )
    session.flush()
    return organization_id, viewer_id, member_id, unrelated_id, review_case


def test_member_display_identity_is_case_scoped_after_case_authorization(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session, session.begin():
        organization_id, viewer_id, member_id, unrelated_id, review_case = _seed_case(session)

    viewer = _actor(viewer_id, organization_id, "Visible Viewer")
    with Session(postgres_engine) as session:
        views = build_review_case_context_query_service(session).list_member_views(
            viewer,
            ReviewCaseId(review_case.id),
        )

    assert {(item.user_id, item.display_name) for item in views} == {
        (viewer_id, "Visible Viewer"),
        (member_id, "Case Member Name"),
    }
    assert unrelated_id not in {item.user_id for item in views}


def test_member_and_activity_reads_refuse_unauthorized_and_foreign_case_access(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session, session.begin():
        organization_id, viewer_id, _member_id, unrelated_id, review_case = _seed_case(session)
        foreign_organization_id = OrganizationId(uuid4())
        foreign_id = UserId(uuid4())
        session.add(
            OrganizationRecord(
                id=foreign_organization_id,
                name=f"Foreign {foreign_organization_id}",
            )
        )
        session.flush()
        session.add(_user(foreign_id, foreign_organization_id, "Foreign User"))

    unrelated = _actor(unrelated_id, organization_id, "Unrelated User")
    foreign = _actor(foreign_id, foreign_organization_id, "Foreign User")
    with Session(postgres_engine) as session:
        service = build_review_case_context_query_service(session)
        with pytest.raises(ReviewAuthorizationError):
            service.list_member_views(unrelated, ReviewCaseId(review_case.id))
        with pytest.raises(ReviewAuthorizationError):
            service.list_case_activities(unrelated, ReviewCaseId(review_case.id))
        with pytest.raises(LookupError):
            service.list_member_views(foreign, ReviewCaseId(review_case.id))
        with pytest.raises(LookupError):
            service.list_case_activities(foreign, ReviewCaseId(review_case.id))


def test_case_activity_read_is_subject_isolated_metadata_free_and_side_effect_free(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session, session.begin():
        organization_id, viewer_id, _member_id, _unrelated_id, review_case = _seed_case(session)
        finding = FindingRecord(
            id=uuid4(),
            organization_id=organization_id,
            case_id=review_case.id,
            title="Child Finding",
            description=None,
            severity="medium",
            lifecycle="rectifying",
            scenario_data_json={},
            raised_by=viewer_id,
            raised_at=NOW,
        )
        session.add(finding)
        session.flush()
        action = ActionItemRecord(
            id=uuid4(),
            organization_id=organization_id,
            finding_id=finding.id,
            title="Child Action",
            lifecycle="todo",
            due_at=None,
            completed_at=None,
        )
        submission = SubmissionRecord(
            id=uuid4(),
            organization_id=organization_id,
            case_id=review_case.id,
            finding_id=None,
            purpose="closure",
            submitted_by=viewer_id,
            submitted_at=NOW,
            payload_json={},
        )
        session.add_all([action, submission])
        session.flush()

        # first/second share occurred_at, so the id decides their order; keep first < second.
        first_id, second_id = sorted([uuid4(), uuid4()], key=lambda value: value.int)
        newest_id = uuid4()
        session.add_all(
            [
                ActivityRecord(
                    id=first_id,
                    organization_id=organization_id,
                    actor_id=viewer_id,
                    event_type="review_case.first",
                    occurred_at=NOW,
                    review_case_id=review_case.id,
                    finding_id=None,
                    action_item_id=None,
                    submission_id=None,
                    metadata_json={"secret": "must-not-cross-wire"},
                ),
                ActivityRecord(
                    id=second_id,
                    organization_id=organization_id,
                    actor_id=viewer_id,
                    event_type="review_case.second",
                    occurred_at=NOW,
                    review_case_id=review_case.id,
                    finding_id=None,
                    action_item_id=None,
                    submission_id=None,
                    metadata_json={"another": "private-value"},
                ),
                ActivityRecord(
                    id=newest_id,
                    organization_id=organization_id,
                    actor_id=None,
                    event_type="review_case.newest",
                    occurred_at=NOW + timedelta(minutes=1),
                    review_case_id=review_case.id,
                    finding_id=None,
                    action_item_id=None,
                    submission_id=None,
                    metadata_json={},
                ),
                ActivityRecord(
                    id=uuid4(),
                    organization_id=organization_id,
                    actor_id=viewer_id,
                    event_type="finding.hidden-child",
                    occurred_at=NOW + timedelta(minutes=2),
                    review_case_id=None,
                    finding_id=finding.id,
                    action_item_id=None,
                    submission_id=None,
                    metadata_json={"hidden": True},
                ),
                ActivityRecord(
                    id=uuid4(),
                    organization_id=organization_id,
                    actor_id=viewer_id,
                    event_type="action.hidden-child",
                    occurred_at=NOW + timedelta(minutes=3),
                    review_case_id=None,
                    finding_id=None,
                    action_item_id=action.id,
                    submission_id=None,
                    metadata_json={"hidden": True},
                ),
                ActivityRecord(
                    id=uuid4(),
                    organization_id=organization_id,
                    actor_id=viewer_id,
                    event_type="submission.hidden-child",
                    occurred_at=NOW + timedelta(minutes=4),
                    review_case_id=None,
                    finding_id=None,
                    action_item_id=None,
                    submission_id=submission.id,
                    metadata_json={"hidden": True},
                ),
            ]
        )
        session.flush()
        activity_count_before = session.scalar(select(func.count()).select_from(ActivityRecord))
        notification_count_before = session.scalar(
            select(func.count()).select_from(NotificationRecord)
        )
        lifecycle_before = review_case.lifecycle

    viewer = _actor(viewer_id, organization_id, "Visible Viewer")
    with Session(postgres_engine) as session:
        views = build_review_case_context_query_service(session).list_case_activities(
            viewer,
            ReviewCaseId(review_case.id),
        )
        activity_count_after = session.scalar(select(func.count()).select_from(ActivityRecord))
        notification_count_after = session.scalar(
            select(func.count()).select_from(NotificationRecord)
        )
        lifecycle_after = session.scalar(
            select(ReviewCaseRecord.lifecycle).where(ReviewCaseRecord.id == review_case.id)
        )

    assert [item.id for item in views] == [newest_id, second_id, first_id]
    assert {item.event_type for item in views} == {
        "review_case.newest",
        "review_case.second",
        "review_case.first",
    }
    assert all(item.subject_id == review_case.id for item in views)
    assert all(not hasattr(item, "metadata") for item in views)
    assert activity_count_after == activity_count_before
    assert notification_count_after == notification_count_before
    assert lifecycle_after == lifecycle_before
