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
    FindingLifecycle,
    FindingParticipant,
    ReviewCase,
    ReviewCaseLifecycle,
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
        organization_id: OrganizationId,
        scenario_id: ScenarioDefinitionId,
        version: ScenarioVersion,
    ) -> ScenarioVersionPublication | None: ...

    def list_for_organization(
        self, organization_id: OrganizationId
    ) -> tuple[ScenarioDefinition, ...]: ...

    def list_versions(
        self,
        organization_id: OrganizationId,
        scenario_id: ScenarioDefinitionId,
    ) -> tuple[ScenarioVersionPublication, ...]: ...


class ReviewCoreRepository(Protocol):
    def add_plan(self, plan: ReviewPlan) -> None: ...

    def get_plan(
        self,
        organization_id: OrganizationId,
        plan_id: ReviewPlanId,
    ) -> ReviewPlan | None: ...

    def list_plans(self, organization_id: OrganizationId) -> tuple[ReviewPlan, ...]: ...

    def add_case(self, review_case: ReviewCase) -> None: ...

    def get_case(
        self,
        organization_id: OrganizationId,
        case_id: ReviewCaseId,
    ) -> ReviewCase | None: ...

    def list_cases(self, organization_id: OrganizationId) -> tuple[ReviewCase, ...]: ...

    def update_case(
        self,
        review_case: ReviewCase,
        *,
        expected_lifecycle: ReviewCaseLifecycle,
    ) -> bool: ...

    def add_case_member(self, member: CaseMember) -> None: ...

    def list_case_members(
        self,
        organization_id: OrganizationId,
        case_id: ReviewCaseId,
    ) -> tuple[CaseMember, ...]: ...

    def add_finding(self, finding: Finding) -> None: ...

    def get_finding(
        self,
        organization_id: OrganizationId,
        finding_id: FindingId,
    ) -> Finding | None: ...

    def list_findings(
        self,
        organization_id: OrganizationId,
        case_id: ReviewCaseId,
    ) -> tuple[Finding, ...]: ...

    def update_finding(
        self,
        finding: Finding,
        *,
        expected_lifecycle: FindingLifecycle,
    ) -> bool: ...

    def add_finding_participant(self, participant: FindingParticipant) -> None: ...

    def list_finding_participants(
        self,
        organization_id: OrganizationId,
        finding_id: FindingId,
    ) -> tuple[FindingParticipant, ...]: ...

    def add_action_item(self, action_item: ActionItem) -> None: ...

    def get_action_item(
        self,
        organization_id: OrganizationId,
        action_item_id: ActionItemId,
    ) -> ActionItem | None: ...

    def add_action_assignee(self, assignee: ActionAssignee) -> None: ...

    def add_submission(self, submission: Submission) -> None: ...

    def get_submission(
        self,
        organization_id: OrganizationId,
        submission_id: SubmissionId,
    ) -> Submission | None: ...

    def add_activity(self, activity: Activity) -> None: ...

    def get_activity(
        self,
        organization_id: OrganizationId,
        activity_id: ActivityId,
    ) -> Activity | None: ...
