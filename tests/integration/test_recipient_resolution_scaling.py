import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from easyaudit_next.collaboration.recipient_resolution import RecipientResolver
from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.persistence.models import UserRecord
from easyaudit_next.review_core.domain.scenario_capabilities import CollaborationRecipientIntent
from easyaudit_next.review_core.persistence.models import ActionAssigneeRecord, FindingRecord
from tests.integration.notification_test_support import NOW
from tests.integration.test_manual_nudge import _seed_nudge_fixture


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _resolve_action_and_count_selects(
    engine: Engine,
    organization_id: OrganizationId,
    finding_id,
    action_item_id,
) -> tuple[int, int]:
    select_count = 0

    def before_cursor_execute(
        _conn,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        with Session(engine) as session:
            finding = session.get(FindingRecord, finding_id)
            assert finding is not None
            resolver = RecipientResolver(session, build_scenario_registry())
            snapshot = resolver.load(organization_id, finding.case_id)
            recipients = resolver.recipients(
                snapshot,
                CollaborationRecipientIntent.ACTION_EXECUTION,
                finding_id=finding.id,
                action_item_id=action_item_id,
            )
            return select_count, len(recipients)
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)


def test_recipient_resolution_query_count_does_not_grow_with_large_candidate_set(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_nudge_fixture(postgres_engine)
    organization_id = OrganizationId(fixture.organization_id)

    small_query_count, small_recipient_count = _resolve_action_and_count_selects(
        postgres_engine,
        organization_id,
        fixture.finding_id,
        fixture.action_item_id,
    )
    assert small_recipient_count == 1

    additional_user_ids = [UserId(uuid4()) for _ in range(100)]
    with Session(postgres_engine) as session, session.begin():
        session.add_all(
            UserRecord(
                id=user_id,
                organization_id=organization_id,
                display_name=f"Scaling recipient {index}",
                platform_role="ordinary_user",
            )
            for index, user_id in enumerate(additional_user_ids)
        )
        session.flush()
        session.add_all(
            ActionAssigneeRecord(
                id=uuid4(),
                organization_id=organization_id,
                action_item_id=fixture.action_item_id,
                user_id=user_id,
                department_id=None,
                role="collaborator",
                assigned_at=NOW,
            )
            for user_id in additional_user_ids
        )

    large_query_count, large_recipient_count = _resolve_action_and_count_selects(
        postgres_engine,
        organization_id,
        fixture.finding_id,
        fixture.action_item_id,
    )

    assert large_recipient_count == 101
    assert large_query_count == small_query_count
    assert large_query_count <= 10
