import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from easyaudit_next.management.query_service import ManagementQueryService
from easyaudit_next.management.schemas import ManagementDeadlineFilter
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.domain.models import User
from easyaudit_next.platform.persistence.models import OrganizationRecord, UserRecord
from easyaudit_next.review_core.domain.models import (
    ReviewCaseLifecycle,
    Scenario,
    ScenarioKey,
    ScenarioVersion,
)
from easyaudit_next.review_core.domain.scenario_capabilities import AuthorizationContext
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
from easyaudit_next.review_core.persistence.models import (
    CaseMemberRecord,
    ReviewCaseRecord,
    ReviewPlanRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)

NOW = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


class _FilterAuthorization:
    def allows(self, permission: str, context: AuthorizationContext) -> bool:
        roles = {grant.role_key for grant in context.case_role_grants}
        if permission in {"view_case", "manage_case_members"}:
            return "manage" in roles
        if permission == "view_finding":
            return True
        return False


class _FilterPolicy:
    scenario = Scenario(
        key=ScenarioKey("management_filter_test"),
        version=ScenarioVersion(1),
        name="Management Filter Test",
    )
    authorization = _FilterAuthorization()


def _registry() -> ScenarioRegistry:
    registry = ScenarioRegistry()
    registry.register(_FilterPolicy())  # type: ignore[arg-type]
    return registry


def _seed_organization(session: Session) -> tuple[OrganizationId, UserId]:
    organization_id = OrganizationId(uuid4())
    user_id = UserId(uuid4())
    session.add(OrganizationRecord(id=organization_id, name=f"Filter {organization_id}"))
    session.flush()
    session.add(
        UserRecord(
            id=user_id,
            organization_id=organization_id,
            display_name="Filter Caller",
            platform_role="ordinary_user",
        )
    )
    session.flush()
    return organization_id, user_id


def test_collection_filters_never_broaden_authorized_management_scope(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session, session.begin():
        organization_id, user_id = _seed_organization(session)
        scenario_id = uuid4()
        version_id = uuid4()
        session.add(
            ScenarioRecord(
                id=scenario_id,
                organization_id=organization_id,
                key="management_filter_test",
                name="Management Filter Test",
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

        plan_one_id = uuid4()
        plan_two_id = uuid4()
        session.add_all(
            [
                ReviewPlanRecord(
                    id=plan_one_id,
                    organization_id=organization_id,
                    title="Plan one",
                    planned_start_at=NOW - timedelta(days=10),
                    planned_end_at=NOW + timedelta(days=10),
                    created_by=user_id,
                    created_at=NOW,
                ),
                ReviewPlanRecord(
                    id=plan_two_id,
                    organization_id=organization_id,
                    title="Plan two",
                    planned_start_at=NOW - timedelta(days=10),
                    planned_end_at=NOW + timedelta(days=30),
                    created_by=user_id,
                    created_at=NOW,
                ),
            ]
        )
        session.flush()

        def managed_case(
            title: str,
            plan_id: object,
            lifecycle: str,
            deadline: datetime,
        ) -> ReviewCaseRecord:
            record = ReviewCaseRecord(
                id=uuid4(),
                organization_id=organization_id,
                plan_id=plan_id,
                scenario_version_id=version_id,
                title=title,
                lifecycle=lifecycle,
                planned_start_at=NOW - timedelta(days=5),
                planned_end_at=deadline,
                started_at=NOW - timedelta(days=2),
                fieldwork_completed_at=None,
                closed_at=None,
                scenario_data_json={},
                created_by=user_id,
                created_at=NOW - timedelta(days=6),
            )
            session.add(record)
            session.flush()
            session.add(
                CaseMemberRecord(
                    organization_id=organization_id,
                    case_id=record.id,
                    user_id=user_id,
                    role_key="manage",
                    joined_at=NOW,
                )
            )
            return record

        overdue = managed_case(
            "Overdue",
            plan_one_id,
            "in_progress",
            NOW - timedelta(days=1),
        )
        due_soon = managed_case(
            "Due soon",
            plan_one_id,
            "scheduled",
            NOW + timedelta(days=1),
        )
        later = managed_case(
            "Later",
            plan_two_id,
            "draft",
            NOW + timedelta(days=20),
        )

        foreign_organization_id, foreign_user_id = _seed_organization(session)
        foreign_plan_id = uuid4()
        session.add(
            ReviewPlanRecord(
                id=foreign_plan_id,
                organization_id=foreign_organization_id,
                title="Foreign plan",
                planned_start_at=None,
                planned_end_at=None,
                created_by=foreign_user_id,
                created_at=NOW,
            )
        )

    actor = User(
        id=user_id,
        organization_id=organization_id,
        display_name="Filter Caller",
    )
    with Session(postgres_engine) as session:
        service = ManagementQueryService(session, _registry())
        plan_page = service.list_review_cases(actor, review_plan_id=plan_one_id, as_of=NOW)
        overdue_page = service.list_review_cases(
            actor,
            deadline_status=ManagementDeadlineFilter.OVERDUE,
            as_of=NOW,
        )
        due_soon_page = service.list_review_cases(
            actor,
            deadline_status=ManagementDeadlineFilter.DUE_SOON,
            as_of=NOW,
        )
        scheduled_page = service.list_review_cases(
            actor,
            lifecycle=ReviewCaseLifecycle.SCHEDULED,
            as_of=NOW,
        )
        foreign_plan_page = service.list_review_cases(
            actor,
            review_plan_id=foreign_plan_id,
            as_of=NOW,
        )

    assert [item.id for item in plan_page.items] == [overdue.id, due_soon.id]
    assert plan_page.total == 2
    assert [item.id for item in overdue_page.items] == [overdue.id]
    assert [item.id for item in due_soon_page.items] == [due_soon.id]
    assert [item.id for item in scheduled_page.items] == [due_soon.id]
    assert foreign_plan_page.items == ()
    assert foreign_plan_page.total == 0
    assert later.id not in {item.id for item in plan_page.items}
