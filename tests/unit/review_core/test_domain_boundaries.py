from datetime import UTC, datetime
from unittest import TestCase
from uuid import UUID, uuid4

from easyaudit_next.review_core.domain.ids import (
    ActionItemId,
    DepartmentId,
    FindingId,
    OrganizationId,
    ReviewCaseId,
    ReviewPlanId,
    UserId,
)
from easyaudit_next.review_core.domain.invariants import (
    assert_plan_contains_case,
    assert_unique_action_assignees,
    assert_unique_finding_participants,
)
from easyaudit_next.review_core.domain.models import (
    ActionAssignee,
    ActionItem,
    ActionItemLifecycle,
    AssignmentRole,
    DepartmentActor,
    FindingParticipant,
    ReviewCase,
    ReviewCaseLifecycle,
    ReviewPlan,
    ScenarioKey,
    ScenarioVersion,
    UserActor,
)

NOW = datetime(2026, 8, 21, tzinfo=UTC)
ORG_ID = OrganizationId(uuid4())
USER_ID = UserId(uuid4())
PLAN_ID = ReviewPlanId(uuid4())


def make_case(
    case_id: UUID,
    scenario_key: str,
    scenario_version: int,
) -> ReviewCase:
    return ReviewCase(
        id=ReviewCaseId(case_id),
        organization_id=ORG_ID,
        plan_id=PLAN_ID,
        scenario_key=ScenarioKey(scenario_key),
        scenario_version=ScenarioVersion(scenario_version),
        title=str(case_id),
        lifecycle=ReviewCaseLifecycle.DRAFT,
        created_by=USER_ID,
        created_at=NOW,
    )


class DomainBoundaryTest(TestCase):
    def test_one_plan_can_contain_cases_from_multiple_scenarios(self) -> None:
        plan = ReviewPlan(
            id=PLAN_ID,
            organization_id=ORG_ID,
            title="2027 年度审查计划",
            planned_start_at=None,
            planned_end_at=None,
            created_by=USER_ID,
        )
        process_case = make_case(uuid4(), "process_review", 1)
        access_case = make_case(uuid4(), "it_access_review", 3)

        assert_plan_contains_case(plan, process_case)
        assert_plan_contains_case(plan, access_case)
        self.assertFalse(hasattr(plan, "scenario_key"))

    def test_action_item_has_many_typed_assignees_instead_of_owner_id(self) -> None:
        action_item = ActionItem(
            id=ActionItemId(uuid4()),
            organization_id=ORG_ID,
            finding_id=FindingId(uuid4()),
            title="修正权限配置",
            lifecycle=ActionItemLifecycle.TODO,
            due_at=None,
        )
        assignees = [
            ActionAssignee(
                organization_id=ORG_ID,
                action_item_id=action_item.id,
                actor=DepartmentActor(DepartmentId(uuid4())),
                role=AssignmentRole.PRIMARY,
                assigned_at=NOW,
            ),
            ActionAssignee(
                organization_id=ORG_ID,
                action_item_id=action_item.id,
                actor=UserActor(UserId(uuid4())),
                role=AssignmentRole.PRIMARY,
                assigned_at=NOW,
            ),
            ActionAssignee(
                organization_id=ORG_ID,
                action_item_id=action_item.id,
                actor=UserActor(UserId(uuid4())),
                role=AssignmentRole.COLLABORATOR,
                assigned_at=NOW,
            ),
        ]

        self.assertFalse(hasattr(action_item, "owner_id"))
        assert_unique_action_assignees(assignees)

    def test_finding_participant_supports_department_and_user(self) -> None:
        participants = [
            FindingParticipant(
                organization_id=ORG_ID,
                finding_id=FindingId(uuid4()),
                actor=DepartmentActor(DepartmentId(uuid4())),
                role_key="responsible_department",
                assigned_at=NOW,
            ),
            FindingParticipant(
                organization_id=ORG_ID,
                finding_id=FindingId(uuid4()),
                actor=UserActor(UserId(uuid4())),
                role_key="primary_owner",
                assigned_at=NOW,
            ),
        ]

        assert_unique_finding_participants(participants)
        with self.assertRaisesRegex(ValueError, "Duplicate FindingParticipant"):
            assert_unique_finding_participants([*participants, participants[0]])
