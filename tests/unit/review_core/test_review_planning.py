from datetime import UTC, datetime
from uuid import uuid4

import pytest

from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.domain.models import PlatformRole, User
from easyaudit_next.review_core.application.review_planning import (
    ReviewAuthorizationError,
    ReviewPlanningService,
)
from easyaudit_next.review_core.domain.ids import ReviewCaseId, ReviewPlanId, ScenarioDefinitionId
from easyaudit_next.review_core.domain.models import (
    CaseMember,
    ReviewCase,
    ReviewPlan,
    ScenarioDefinition,
    ScenarioKey,
    ScenarioVersion,
    ScenarioVersionPublication,
)

NOW = datetime(2026, 8, 21, tzinfo=UTC)


class InMemoryRepository:
    def __init__(self) -> None:
        self.plans: dict[ReviewPlanId, ReviewPlan] = {}
        self.cases: dict[ReviewCaseId, ReviewCase] = {}
        self.members: list[CaseMember] = []
        self.activities: list[object] = []

    def add_plan(self, plan: ReviewPlan) -> None:
        self.plans[plan.id] = plan

    def get_plan(self, organization_id: OrganizationId, plan_id: ReviewPlanId) -> ReviewPlan | None:
        plan = self.plans.get(plan_id)
        return plan if plan is not None and plan.organization_id == organization_id else None

    def list_plans(self, organization_id: OrganizationId) -> tuple[ReviewPlan, ...]:
        return tuple(plan for plan in self.plans.values() if plan.organization_id == organization_id)

    def add_case(self, review_case: ReviewCase) -> None:
        self.cases[review_case.id] = review_case

    def get_case(
        self, organization_id: OrganizationId, case_id: ReviewCaseId
    ) -> ReviewCase | None:
        review_case = self.cases.get(case_id)
        return (
            review_case
            if review_case is not None and review_case.organization_id == organization_id
            else None
        )

    def list_cases(self, organization_id: OrganizationId) -> tuple[ReviewCase, ...]:
        return tuple(
            review_case
            for review_case in self.cases.values()
            if review_case.organization_id == organization_id
        )

    def update_case(self, review_case: ReviewCase) -> None:
        self.cases[review_case.id] = review_case

    def add_case_member(self, member: CaseMember) -> None:
        self.members.append(member)

    def list_case_members(
        self, organization_id: OrganizationId, case_id: ReviewCaseId
    ) -> tuple[CaseMember, ...]:
        return tuple(
            member
            for member in self.members
            if member.organization_id == organization_id and member.case_id == case_id
        )

    def add_activity(self, activity: object) -> None:
        self.activities.append(activity)


class Catalog:
    def __init__(self, organization_id: OrganizationId) -> None:
        self.organization_id = organization_id
        self.scenario = ScenarioDefinition(
            id=ScenarioDefinitionId(uuid4()),
            organization_id=organization_id,
            key=ScenarioKey("process_review"),
            name="Process Review",
        )
        self.version = ScenarioVersionPublication(
            id=uuid4(),  # type: ignore[arg-type]
            scenario_id=self.scenario.id,
            organization_id=organization_id,
            version=ScenarioVersion(1),
            published_at=NOW,
        )

    def get_by_key(
        self, organization_id: OrganizationId, key: ScenarioKey
    ) -> ScenarioDefinition | None:
        if organization_id == self.organization_id and key == self.scenario.key:
            return self.scenario
        return None

    def get_version(
        self,
        organization_id: OrganizationId,
        scenario_id: ScenarioDefinitionId,
        version: ScenarioVersion,
    ) -> ScenarioVersionPublication | None:
        if (
            organization_id == self.organization_id
            and scenario_id == self.scenario.id
            and version == self.version.version
        ):
            return self.version
        return None


class Users:
    def __init__(self, *users: User) -> None:
        self.users = {user.id: user for user in users}

    def get(self, user_id: UserId) -> User | None:
        return self.users.get(user_id)


def _user(organization_id: OrganizationId, *, active: bool = True) -> User:
    return User(
        id=UserId(uuid4()),
        organization_id=organization_id,
        display_name="User",
        platform_role=PlatformRole.ORDINARY_USER,
        is_active=active,
    )


def test_creator_becomes_lead_without_review_core_knowing_scenario_key_rules() -> None:
    organization_id = OrganizationId(uuid4())
    creator = _user(organization_id)
    repository = InMemoryRepository()
    service = ReviewPlanningService(
        repository,  # type: ignore[arg-type]
        Catalog(organization_id),  # type: ignore[arg-type]
        Users(creator),  # type: ignore[arg-type]
        build_scenario_registry(),
    )

    review_case = service.create_case(
        creator,
        ScenarioKey("process_review"),
        ScenarioVersion(1),
        "Assembly Review",
        {"area_code": "ASSY", "review_type": "routine"},
        occurred_at=NOW,
    )

    assert review_case.lifecycle.value == "draft"
    assert repository.members == [
        CaseMember(organization_id, review_case.id, creator.id, "lead", NOW)
    ]
    assert len(repository.activities) == 1


def test_inactive_user_cannot_create_plan_or_case() -> None:
    organization_id = OrganizationId(uuid4())
    actor = _user(organization_id, active=False)
    repository = InMemoryRepository()
    service = ReviewPlanningService(
        repository,  # type: ignore[arg-type]
        Catalog(organization_id),  # type: ignore[arg-type]
        Users(actor),  # type: ignore[arg-type]
        build_scenario_registry(),
    )

    with pytest.raises(ReviewAuthorizationError):
        service.create_plan(actor, "Plan")
    with pytest.raises(ReviewAuthorizationError):
        service.create_case(
            actor,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            "Case",
            {"area_code": "ASSY", "review_type": "routine"},
        )
