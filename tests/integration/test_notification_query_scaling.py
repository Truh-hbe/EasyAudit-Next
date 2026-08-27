import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_finding_lifecycle_service,
    build_notification_orchestrator,
    build_rectification_service,
    build_review_planning_service,
)
from easyaudit_next.platform.domain.ids import UserId
from easyaudit_next.platform.persistence.models import UserRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.mutation_results import RectificationSubmissionResult
from easyaudit_next.review_core.domain.models import (
    AssignmentRole,
    DepartmentActor,
    FindingSeverity,
    ScenarioKey,
    ScenarioVersion,
    UserActor,
)
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


def _verification_result(
    engine: Engine,
) -> tuple[object, RectificationSubmissionResult]:
    organization_id, department_id, ids = seed_process_review_users(engine)
    with Session(engine, expire_on_commit=False) as session:
        users = SqlAlchemyUserRepository(session)
        lead = users.get(ids["lead"])
        owner = users.get(ids["owner"])
        action_assignee = users.get(ids["action_assignee"])
        assert lead is not None
        assert owner is not None
        assert action_assignee is not None

        planning = build_review_planning_service(session)
        review_case = planning.create_case(
            lead,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            "Notification query scaling",
            {"area_code": "ASSY", "review_type": "routine"},
            occurred_at=NOW,
        )
        planning.add_case_member(
            lead,
            review_case.id,
            ids["reviewer"],
            "reviewer",
            occurred_at=NOW,
        )
        planning.transition_case(lead, review_case.id, "schedule", occurred_at=NOW)
        planning.transition_case(lead, review_case.id, "start", occurred_at=NOW)

        findings = build_finding_lifecycle_service(session)
        finding = findings.create_finding(
            lead,
            review_case.id,
            "Scaling finding",
            FindingSeverity.HIGH,
            {"issue_type": "control_gap", "project_category": "assembly"},
            occurred_at=NOW,
        )
        findings.add_participant(
            lead,
            finding.id,
            UserActor(owner.id),
            "owner",
            occurred_at=NOW,
        )
        findings.add_participant(
            lead,
            finding.id,
            DepartmentActor(department_id),
            "responsible_department",
            occurred_at=NOW,
        )
        findings.transition_finding(lead, finding.id, "issue", occurred_at=NOW)

        rectification = build_rectification_service(session)
        action_item = rectification.create_action_item(
            owner,
            finding.id,
            "Scaling action",
            occurred_at=NOW,
        )
        rectification.add_assignee(
            owner,
            action_item.id,
            UserActor(action_assignee.id),
            AssignmentRole.PRIMARY,
            occurred_at=NOW,
        )
        rectification.transition_action_item(
            action_assignee,
            action_item.id,
            "start",
            occurred_at=NOW,
        )
        rectification.transition_action_item(
            action_assignee,
            action_item.id,
            "complete",
            occurred_at=NOW,
        )
        result = rectification.submit_rectification_result(
            owner,
            finding.id,
            "submit_for_verification",
            {"stage": "completion", "comment": "Ready"},
            occurred_at=NOW,
        )
        session.commit()
        return organization_id, result


def _count_verification_selects(
    engine: Engine,
    result: RectificationSubmissionResult,
) -> int:
    count = 0

    def before_cursor_execute(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal count
        if statement.lstrip().upper().startswith("SELECT"):
            count += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        with Session(engine) as session:
            build_notification_orchestrator(session).rectification_submitted(result)
            session.rollback()
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return count


def test_verification_recipient_queries_are_category_bounded_not_user_bounded(
    postgres_engine: Engine,
) -> None:
    organization_id, result = _verification_result(postgres_engine)
    small_count = _count_verification_selects(postgres_engine, result)

    with Session(postgres_engine) as session, session.begin():
        session.add_all(
            [
                UserRecord(
                    id=UserId(uuid4()),
                    organization_id=organization_id,
                    display_name=f"Unrelated candidate {index}",
                    platform_role="ordinary_user",
                )
                for index in range(100)
            ]
        )

    large_count = _count_verification_selects(postgres_engine, result)

    assert small_count <= 8
    assert large_count == small_count
