import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_notification_orchestrator,
    build_review_planning_service,
)
from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.platform.domain.ids import UserId
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.domain.ids import ActivityId
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


def test_same_subject_same_event_type_concurrency_cannot_cross_bind_activity(
    postgres_engine: Engine,
) -> None:
    organization_id, _, ids = seed_process_review_users(postgres_engine)

    with Session(postgres_engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(ids["lead"])
        assert lead is not None
        review_case = build_review_planning_service(session).create_case(
            lead,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            "Concurrent provenance case",
            {"area_code": "ASSY", "review_type": "routine"},
            occurred_at=NOW,
        )
        case_id = review_case.id
        session.commit()

    barrier = Barrier(2)

    def add_observer(target_user_id: UserId) -> tuple[UserId, ActivityId]:
        with Session(postgres_engine) as session:
            lead = SqlAlchemyUserRepository(session).get(ids["lead"])
            assert lead is not None
            barrier.wait()
            result = build_review_planning_service(session).add_case_member_result(
                lead,
                case_id,
                target_user_id,
                "observer",
                occurred_at=NOW,
            )
            build_notification_orchestrator(session).case_member_added(result)
            session.commit()
            return target_user_id, result.activity_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(add_observer, ids["observer_a"])
        future_b = executor.submit(add_observer, ids["observer_b"])
        results = [future_a.result(timeout=10), future_b.result(timeout=10)]

    expected = dict(results)
    targets = tuple(expected)
    with Session(postgres_engine) as verification:
        notifications = tuple(
            verification.scalars(
                select(NotificationRecord).where(
                    NotificationRecord.organization_id == organization_id,
                    NotificationRecord.review_case_id == case_id,
                    NotificationRecord.kind == NotificationKind.CASE_MEMBERSHIP_ADDED.value,
                    NotificationRecord.recipient_user_id.in_(targets),
                )
            )
        )
        assert len(notifications) == 2

        for notification in notifications:
            recipient_id = UserId(notification.recipient_user_id)
            assert notification.origin_activity_id == expected[recipient_id]
            activity = verification.get(ActivityRecord, notification.origin_activity_id)
            assert activity is not None
            assert activity.review_case_id == case_id
            assert activity.event_type == "review_case.member_added"
            assert activity.occurred_at == NOW
            assert activity.metadata_json["user_id"] == str(recipient_id)
