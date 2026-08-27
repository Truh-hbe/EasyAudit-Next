import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_notification_orchestrator,
    build_notification_service,
    build_review_planning_service,
)
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.domain.models import ScenarioKey, ScenarioVersion
from easyaudit_next.review_core.persistence.models import ActivityRecord
from tests.integration.notification_test_support import (
    NOW,
    seed_process_review_users,
)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _create_membership_notification(
    engine: Engine,
) -> tuple[object, object, object, object]:
    organization_id, _, ids = seed_process_review_users(engine)
    with Session(engine, expire_on_commit=False) as session:
        users = SqlAlchemyUserRepository(session)
        lead = users.get(ids["lead"])
        reviewer = users.get(ids["reviewer"])
        assert lead is not None
        assert reviewer is not None

        planning = build_review_planning_service(session)
        review_case = planning.create_case(
            lead,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            "Inbox isolation case",
            {"area_code": "ASSY", "review_type": "routine"},
            occurred_at=NOW,
        )
        result = planning.add_case_member_result(
            lead,
            review_case.id,
            reviewer.id,
            "reviewer",
            occurred_at=NOW,
        )
        build_notification_orchestrator(session).case_member_added(result)
        session.commit()

        page = build_notification_service(session).get_inbox(
            organization_id,
            reviewer.id,
            limit=100,
            offset=0,
        )
        notification = next(
            item for item in page.items if item.origin_activity_id == result.activity_id
        )
        return organization_id, reviewer.id, ids["unrelated"], notification.id


def test_known_foreign_notification_uuid_cannot_cross_recipient_or_organization(
    postgres_engine: Engine,
) -> None:
    org_a, reviewer_a, unrelated_a, notification_a = _create_membership_notification(
        postgres_engine
    )
    org_b, reviewer_b, _, notification_b = _create_membership_notification(postgres_engine)

    with Session(postgres_engine) as session:
        service = build_notification_service(session)
        page_a = service.get_inbox(org_a, reviewer_a, limit=100, offset=0)
        page_b = service.get_inbox(org_b, reviewer_b, limit=100, offset=0)
        unrelated_page = service.get_inbox(org_a, unrelated_a, limit=100, offset=0)
        cross_org_page = service.get_inbox(org_a, reviewer_b, limit=100, offset=0)

        assert {item.id for item in page_a.items} == {notification_a}
        assert {item.id for item in page_b.items} == {notification_b}
        assert unrelated_page.items == ()
        assert cross_org_page.items == ()

        with pytest.raises(LookupError, match="Notification not found"):
            service.mark_read(org_a, unrelated_a, notification_a)
        with pytest.raises(LookupError, match="Notification not found"):
            service.mark_read(org_b, reviewer_b, notification_a)
        with pytest.raises(LookupError, match="Notification not found"):
            service.mark_read(org_a, reviewer_b, notification_a)


def test_mark_read_changes_only_recipient_local_read_state_and_no_review_activity(
    postgres_engine: Engine,
) -> None:
    organization_id, reviewer_id, _, notification_id = _create_membership_notification(
        postgres_engine
    )

    with Session(postgres_engine) as session, session.begin():
        before_activity_count = session.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(ActivityRecord.organization_id == organization_id)
        )
        service = build_notification_service(session)
        first = service.mark_read(organization_id, reviewer_id, notification_id)
        second = service.mark_read(organization_id, reviewer_id, notification_id)
        after_activity_count = session.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(ActivityRecord.organization_id == organization_id)
        )

        assert first.read_at is not None
        assert second.read_at == first.read_at
        assert after_activity_count == before_activity_count
