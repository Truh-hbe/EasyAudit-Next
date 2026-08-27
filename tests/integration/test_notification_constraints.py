import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_review_planning_service
from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.notifications.persistence import NotificationRecord
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


def _seed_case_with_origin(engine: Engine) -> tuple[object, object, object, ActivityId]:
    organization_id, _, ids = seed_process_review_users(engine)
    with Session(engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(ids["lead"])
        assert lead is not None
        review_case = build_review_planning_service(session).create_case(
            lead,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            "Notification constraint case",
            {"area_code": "ASSY", "review_type": "routine"},
            occurred_at=NOW,
        )
        activity_id = ActivityId(uuid4())
        session.add(
            ActivityRecord(
                id=activity_id,
                organization_id=organization_id,
                actor_id=lead.id,
                event_type="notification.constraint.origin",
                occurred_at=NOW,
                review_case_id=review_case.id,
                metadata_json={},
            )
        )
        session.commit()
        return organization_id, lead.id, review_case.id, activity_id


def _notification_record(
    *,
    organization_id: object,
    recipient_user_id: object,
    origin_activity_id: object,
    review_case_id: object | None = None,
    finding_id: object | None = None,
) -> NotificationRecord:
    return NotificationRecord(
        id=uuid4(),
        organization_id=organization_id,
        recipient_user_id=recipient_user_id,
        kind=NotificationKind.CASE_MEMBERSHIP_ADDED.value,
        origin_activity_id=origin_activity_id,
        review_case_id=review_case_id,
        finding_id=finding_id,
        title="Constraint test",
        body="Constraint test body",
        created_at=NOW,
    )


def test_notification_rejects_cross_organization_recipient(
    postgres_engine: Engine,
) -> None:
    org_a, _, case_a, activity_a = _seed_case_with_origin(postgres_engine)
    _, recipient_b, _, _ = _seed_case_with_origin(postgres_engine)

    with pytest.raises(IntegrityError):
        with Session(postgres_engine) as session, session.begin():
            session.add(
                _notification_record(
                    organization_id=org_a,
                    recipient_user_id=recipient_b,
                    origin_activity_id=activity_a,
                    review_case_id=case_a,
                )
            )
            session.flush()


def test_notification_rejects_cross_organization_subject(
    postgres_engine: Engine,
) -> None:
    org_a, recipient_a, _, activity_a = _seed_case_with_origin(postgres_engine)
    _, _, case_b, _ = _seed_case_with_origin(postgres_engine)

    with pytest.raises(IntegrityError):
        with Session(postgres_engine) as session, session.begin():
            session.add(
                _notification_record(
                    organization_id=org_a,
                    recipient_user_id=recipient_a,
                    origin_activity_id=activity_a,
                    review_case_id=case_b,
                )
            )
            session.flush()


def test_notification_requires_exactly_one_typed_subject(
    postgres_engine: Engine,
) -> None:
    organization_id, recipient_id, case_id, activity_id = _seed_case_with_origin(
        postgres_engine
    )

    with pytest.raises(IntegrityError):
        with Session(postgres_engine) as session, session.begin():
            session.add(
                _notification_record(
                    organization_id=organization_id,
                    recipient_user_id=recipient_id,
                    origin_activity_id=activity_id,
                )
            )
            session.flush()

    with pytest.raises(IntegrityError):
        with Session(postgres_engine) as session, session.begin():
            session.add(
                _notification_record(
                    organization_id=organization_id,
                    recipient_user_id=recipient_id,
                    origin_activity_id=activity_id,
                    review_case_id=case_id,
                    finding_id=uuid4(),
                )
            )
            session.flush()
