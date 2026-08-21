from typing import Protocol

from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.review_core.domain.ids import (
    ActionItemId,
    ActivityId,
    FindingId,
    ReviewCaseId,
    ReviewPlanId,
    ScenarioDefinitionId,
    SubmissionId,
)
from easyaudit_next.review_core.domain.models import (
    ActionAssignee,
    ActionItem,
    Activity,
    CaseMember,
    Finding,
    FindingParticipant,
    ReviewCase,
    ReviewPlan,
    ScenarioDefinition,
    ScenarioKey,
    ScenarioVersion,
    ScenarioVersionPublication,
    Submission,
)


class ScenarioCatalogRepository(Protocol):
    def add_scenario(self, scenario: ScenarioDefinition) -> None: ...

    def add_version(self, publication: ScenarioVersionPublication) -> None: ...

    def get_by_key(
        self,
        organization_id: OrganizationId,
        key: ScenarioKey,
    ) -> ScenarioDefinition | None: ...

    def get_version(
        self,
        scenario_id: ScenarioDefinitionId,
        version: ScenarioVersion,
    ) -> ScenarioVersionPublication | None: ...

    def list_for_organization(
        self, organization_id: OrganizationId
    ) -> tuple[ScenarioDefinition, ...]: ...

    def list_versions(
        self, scenario_id: ScenarioDefinitionId
    ) -> tuple[ScenarioVersionPublication, ...]: ...


class ReviewCoreRepository(Protocol):
    def add_plan(self, plan: ReviewPlan) -> None: ...

    def get_plan(self, plan_id: ReviewPlanId) -> ReviewPlan | None: ...

    def add_case(self, review_case: ReviewCase) -> None: ...

    def get_case(self, case_id: ReviewCaseId) -> ReviewCase | None: ...

    def add_case_member(self, member: CaseMember) -> None: ...

    def add_finding(self, finding: Finding) -> None: ...

    def get_finding(self, finding_id: FindingId) -> Finding | None: ...

    def add_finding_participant(self, participant: FindingParticipant) -> None: ...

    def add_action_item(self, action_item: ActionItem) -> None: ...

    def get_action_item(self, action_item_id: ActionItemId) -> ActionItem | None: ...

    def add_action_assignee(self, assignee: ActionAssignee) -> None: ...

    def add_submission(self, submission: Submission) -> None: ...

    def get_submission(self, submission_id: SubmissionId) -> Submission | None: ...

    def add_activity(self, activity: Activity) -> None: ...

    def get_activity(self, activity_id: ActivityId) -> Activity | None: ...
