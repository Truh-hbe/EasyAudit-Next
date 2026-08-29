from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.review_core.domain.ids import (
    ActionItemId,
    ActivityId,
    FindingId,
    ReviewCaseId,
    ReviewPlanId,
    ScenarioDefinitionId,
    ScenarioVersionId,
    SubmissionId,
)
from easyaudit_next.review_core.domain.models import (
    ActionAssignee,
    ActionItem,
    ActionItemActivitySubject,
    ActionItemLifecycle,
    Activity,
    ActivitySubject,
    CaseMember,
    DepartmentActor,
    Finding,
    FindingActivitySubject,
    FindingLifecycle,
    FindingParticipant,
    FindingSeverity,
    ParticipantActor,
    ReviewCase,
    ReviewCaseActivitySubject,
    ReviewCaseLifecycle,
    ReviewPlan,
    ScenarioDefinition,
    ScenarioKey,
    ScenarioVersion,
    ScenarioVersionPublication,
    Submission,
    SubmissionActivitySubject,
    SubmissionPurpose,
    UserActor,
)
from easyaudit_next.review_core.persistence.models import (
    ActionAssigneeRecord,
    ActionItemRecord,
    ActivityRecord,
    CaseMemberRecord,
    FindingParticipantRecord,
    FindingRecord,
    ReviewCaseRecord,
    ReviewPlanRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
    SubmissionRecord,
)


class SqlAlchemyScenarioCatalogRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_scenario(self, scenario: ScenarioDefinition) -> None:
        self._session.add(
            ScenarioRecord(
                id=scenario.id,
                organization_id=scenario.organization_id,
                key=scenario.key,
                name=scenario.name,
                is_active=scenario.is_active,
            )
        )
        self._session.flush()

    def add_version(self, publication: ScenarioVersionPublication) -> None:
        self._session.add(
            ScenarioVersionRecord(
                id=publication.id,
                scenario_id=publication.scenario_id,
                organization_id=publication.organization_id,
                version=publication.version,
                published_at=publication.published_at,
            )
        )
        self._session.flush()

    def get_by_key(
        self,
        organization_id: OrganizationId,
        key: ScenarioKey,
    ) -> ScenarioDefinition | None:
        record = self._session.scalar(
            select(ScenarioRecord).where(
                ScenarioRecord.organization_id == organization_id,
                ScenarioRecord.key == key,
            )
        )
        if record is None:
            return None
        return self._scenario_to_domain(record)

    def get_version(
        self,
        organization_id: OrganizationId,
        scenario_id: ScenarioDefinitionId,
        version: ScenarioVersion,
    ) -> ScenarioVersionPublication | None:
        record = self._session.scalar(
            select(ScenarioVersionRecord).where(
                ScenarioVersionRecord.organization_id == organization_id,
                ScenarioVersionRecord.scenario_id == scenario_id,
                ScenarioVersionRecord.version == version,
            )
        )
        if record is None:
            return None
        return self._version_to_domain(record)

    def list_for_organization(
        self, organization_id: OrganizationId
    ) -> tuple[ScenarioDefinition, ...]:
        records = self._session.scalars(
            select(ScenarioRecord)
            .where(ScenarioRecord.organization_id == organization_id)
            .order_by(ScenarioRecord.key)
        )
        return tuple(self._scenario_to_domain(record) for record in records)

    def list_versions(
        self,
        organization_id: OrganizationId,
        scenario_id: ScenarioDefinitionId,
    ) -> tuple[ScenarioVersionPublication, ...]:
        records = self._session.scalars(
            select(ScenarioVersionRecord)
            .where(
                ScenarioVersionRecord.organization_id == organization_id,
                ScenarioVersionRecord.scenario_id == scenario_id,
            )
            .order_by(ScenarioVersionRecord.version)
        )
        return tuple(self._version_to_domain(record) for record in records)

    @staticmethod
    def _scenario_to_domain(record: ScenarioRecord) -> ScenarioDefinition:
        return ScenarioDefinition(
            id=ScenarioDefinitionId(record.id),
            organization_id=OrganizationId(record.organization_id),
            key=ScenarioKey(record.key),
            name=record.name,
            is_active=record.is_active,
        )

    @staticmethod
    def _version_to_domain(record: ScenarioVersionRecord) -> ScenarioVersionPublication:
        return ScenarioVersionPublication(
            id=ScenarioVersionId(record.id),
            scenario_id=ScenarioDefinitionId(record.scenario_id),
            organization_id=OrganizationId(record.organization_id),
            version=ScenarioVersion(record.version),
            published_at=record.published_at,
        )


class SqlAlchemyReviewCoreRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_plan(self, plan: ReviewPlan) -> None:
        self._session.add(
            ReviewPlanRecord(
                id=plan.id,
                organization_id=plan.organization_id,
                title=plan.title,
                planned_start_at=plan.planned_start_at,
                planned_end_at=plan.planned_end_at,
                created_by=plan.created_by,
            )
        )
        self._session.flush()

    def get_plan(
        self,
        organization_id: OrganizationId,
        plan_id: ReviewPlanId,
    ) -> ReviewPlan | None:
        record = self._session.scalar(
            select(ReviewPlanRecord).where(
                ReviewPlanRecord.organization_id == organization_id,
                ReviewPlanRecord.id == plan_id,
            )
        )
        return self._plan_to_domain(record) if record is not None else None

    def list_plans(self, organization_id: OrganizationId) -> tuple[ReviewPlan, ...]:
        records = self._session.scalars(
            select(ReviewPlanRecord)
            .where(ReviewPlanRecord.organization_id == organization_id)
            .order_by(ReviewPlanRecord.created_at.desc())
        )
        return tuple(self._plan_to_domain(record) for record in records)

    @staticmethod
    def _plan_to_domain(record: ReviewPlanRecord) -> ReviewPlan:
        return ReviewPlan(
            id=ReviewPlanId(record.id),
            organization_id=OrganizationId(record.organization_id),
            title=record.title,
            planned_start_at=record.planned_start_at,
            planned_end_at=record.planned_end_at,
            created_by=UserId(record.created_by),
        )

    def add_case(self, review_case: ReviewCase) -> None:
        scenario_version_id = self._session.scalar(
            select(ScenarioVersionRecord.id)
            .join(ScenarioRecord, ScenarioRecord.id == ScenarioVersionRecord.scenario_id)
            .where(
                ScenarioVersionRecord.organization_id == review_case.organization_id,
                ScenarioRecord.organization_id == review_case.organization_id,
                ScenarioRecord.key == review_case.scenario_key,
                ScenarioVersionRecord.version == review_case.scenario_version,
            )
        )
        if scenario_version_id is None:
            raise LookupError(
                "Published Scenario version does not exist: "
                f"{review_case.scenario_key}@{review_case.scenario_version}"
            )
        self._session.add(
            ReviewCaseRecord(
                id=review_case.id,
                organization_id=review_case.organization_id,
                plan_id=review_case.plan_id,
                scenario_version_id=scenario_version_id,
                title=review_case.title,
                lifecycle=review_case.lifecycle.value,
                planned_start_at=review_case.planned_start_at,
                planned_end_at=review_case.planned_end_at,
                started_at=review_case.started_at,
                fieldwork_completed_at=review_case.fieldwork_completed_at,
                closed_at=review_case.closed_at,
                scenario_data_json=dict(review_case.scenario_data),
                created_by=review_case.created_by,
                created_at=review_case.created_at,
            )
        )
        self._session.flush()

    def get_case(
        self,
        organization_id: OrganizationId,
        case_id: ReviewCaseId,
    ) -> ReviewCase | None:
        record = self._session.scalar(
            select(ReviewCaseRecord).where(
                ReviewCaseRecord.organization_id == organization_id,
                ReviewCaseRecord.id == case_id,
            )
        )
        return self._case_to_domain(record) if record is not None else None

    def list_cases(self, organization_id: OrganizationId) -> tuple[ReviewCase, ...]:
        records = self._session.scalars(
            select(ReviewCaseRecord)
            .where(ReviewCaseRecord.organization_id == organization_id)
            .order_by(ReviewCaseRecord.created_at.desc())
        )
        return tuple(self._case_to_domain(record) for record in records)

    def lock_case_for_team_management(
        self,
        organization_id: OrganizationId,
        case_id: ReviewCaseId,
    ) -> ReviewCase | None:
        record = self._session.scalar(
            select(ReviewCaseRecord)
            .where(
                ReviewCaseRecord.organization_id == organization_id,
                ReviewCaseRecord.id == case_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._case_to_domain(record) if record is not None else None

    def list_cases_for_member(
        self,
        organization_id: OrganizationId,
        user_id: UserId,
    ) -> tuple[ReviewCase, ...]:
        records = self._session.scalars(
            select(ReviewCaseRecord)
            .join(
                CaseMemberRecord,
                (CaseMemberRecord.case_id == ReviewCaseRecord.id)
                & (CaseMemberRecord.organization_id == ReviewCaseRecord.organization_id),
            )
            .where(
                ReviewCaseRecord.organization_id == organization_id,
                CaseMemberRecord.user_id == user_id,
            )
            .distinct()
            .order_by(ReviewCaseRecord.id)
            .execution_options(populate_existing=True)
        )
        return tuple(self._case_to_domain(record) for record in records)

    def _case_to_domain(self, record: ReviewCaseRecord) -> ReviewCase:
        version = self._session.scalar(
            select(ScenarioVersionRecord).where(
                ScenarioVersionRecord.organization_id == record.organization_id,
                ScenarioVersionRecord.id == record.scenario_version_id,
            )
        )
        if version is None:
            raise LookupError("ReviewCase has no Scenario version")
        scenario = self._session.scalar(
            select(ScenarioRecord).where(
                ScenarioRecord.organization_id == record.organization_id,
                ScenarioRecord.id == version.scenario_id,
            )
        )
        if scenario is None:
            raise LookupError("ScenarioVersion has no Scenario")
        return ReviewCase(
            id=ReviewCaseId(record.id),
            organization_id=OrganizationId(record.organization_id),
            plan_id=ReviewPlanId(record.plan_id) if record.plan_id is not None else None,
            scenario_key=ScenarioKey(scenario.key),
            scenario_version=ScenarioVersion(version.version),
            title=record.title,
            lifecycle=ReviewCaseLifecycle(record.lifecycle),
            created_by=UserId(record.created_by),
            created_at=record.created_at,
            planned_start_at=record.planned_start_at,
            planned_end_at=record.planned_end_at,
            started_at=record.started_at,
            fieldwork_completed_at=record.fieldwork_completed_at,
            closed_at=record.closed_at,
            scenario_data=record.scenario_data_json,
        )

    def update_case(
        self,
        review_case: ReviewCase,
        *,
        expected_lifecycle: ReviewCaseLifecycle,
    ) -> bool:
        matched_id: object | None = self._session.scalar(
            update(ReviewCaseRecord)
            .where(
                ReviewCaseRecord.organization_id == review_case.organization_id,
                ReviewCaseRecord.id == review_case.id,
                ReviewCaseRecord.lifecycle == expected_lifecycle.value,
            )
            .values(
                title=review_case.title,
                lifecycle=review_case.lifecycle.value,
                planned_start_at=review_case.planned_start_at,
                planned_end_at=review_case.planned_end_at,
                started_at=review_case.started_at,
                fieldwork_completed_at=review_case.fieldwork_completed_at,
                closed_at=review_case.closed_at,
                scenario_data_json=dict(review_case.scenario_data),
            )
            .returning(ReviewCaseRecord.id)
            .execution_options(synchronize_session="fetch")
        )
        self._session.flush()
        return matched_id is not None

    def add_case_member(self, member: CaseMember) -> None:
        self._session.add(
            CaseMemberRecord(
                organization_id=member.organization_id,
                case_id=member.case_id,
                user_id=member.user_id,
                role_key=member.role_key,
                joined_at=member.joined_at,
            )
        )
        self._session.flush()

    def list_case_members(
        self,
        organization_id: OrganizationId,
        case_id: ReviewCaseId,
    ) -> tuple[CaseMember, ...]:
        records = self._session.scalars(
            select(CaseMemberRecord)
            .where(
                CaseMemberRecord.organization_id == organization_id,
                CaseMemberRecord.case_id == case_id,
            )
            .order_by(CaseMemberRecord.joined_at, CaseMemberRecord.role_key)
        )
        return tuple(
            CaseMember(
                organization_id=OrganizationId(record.organization_id),
                case_id=ReviewCaseId(record.case_id),
                user_id=UserId(record.user_id),
                role_key=record.role_key,
                joined_at=record.joined_at,
            )
            for record in records
        )

    def remove_case_member(
        self,
        organization_id: OrganizationId,
        case_id: ReviewCaseId,
        user_id: UserId,
        role_key: str,
    ) -> bool:
        result = self._session.execute(
            delete(CaseMemberRecord)
            .where(
                CaseMemberRecord.organization_id == organization_id,
                CaseMemberRecord.case_id == case_id,
                CaseMemberRecord.user_id == user_id,
                CaseMemberRecord.role_key == role_key,
            )
            .returning(CaseMemberRecord.user_id)
        )
        self._session.flush()
        return result.scalar_one_or_none() is not None

    def add_finding(self, finding: Finding) -> None:
        self._session.add(
            FindingRecord(
                id=finding.id,
                organization_id=finding.organization_id,
                case_id=finding.case_id,
                title=finding.title,
                description=finding.description,
                severity=finding.severity.value,
                lifecycle=finding.lifecycle.value,
                raised_by=finding.raised_by,
                raised_at=finding.raised_at,
                scenario_data_json=dict(finding.scenario_data),
            )
        )
        self._session.flush()

    def get_finding(
        self,
        organization_id: OrganizationId,
        finding_id: FindingId,
    ) -> Finding | None:
        record = self._session.scalar(
            select(FindingRecord).where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.id == finding_id,
            )
        )
        if record is None:
            return None
        return self._finding_to_domain(record)

    def list_findings(
        self,
        organization_id: OrganizationId,
        case_id: ReviewCaseId,
    ) -> tuple[Finding, ...]:
        records = self._session.scalars(
            select(FindingRecord)
            .where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.case_id == case_id,
            )
            .order_by(FindingRecord.raised_at.desc(), FindingRecord.id)
        )
        return tuple(self._finding_to_domain(record) for record in records)

    @staticmethod
    def _finding_to_domain(record: FindingRecord) -> Finding:
        return Finding(
            id=FindingId(record.id),
            organization_id=OrganizationId(record.organization_id),
            case_id=ReviewCaseId(record.case_id),
            title=record.title,
            description=record.description,
            severity=FindingSeverity(record.severity),
            lifecycle=FindingLifecycle(record.lifecycle),
            raised_by=UserId(record.raised_by),
            raised_at=record.raised_at,
            scenario_data=record.scenario_data_json,
        )

    def update_finding(
        self,
        finding: Finding,
        *,
        expected_lifecycle: FindingLifecycle,
    ) -> bool:
        matched_id: object | None = self._session.scalar(
            update(FindingRecord)
            .where(
                FindingRecord.organization_id == finding.organization_id,
                FindingRecord.id == finding.id,
                FindingRecord.lifecycle == expected_lifecycle.value,
            )
            .values(lifecycle=finding.lifecycle.value)
            .returning(FindingRecord.id)
            .execution_options(synchronize_session="fetch")
        )
        self._session.flush()
        return matched_id is not None

    def add_finding_participant(self, participant: FindingParticipant) -> None:
        user_id = participant.actor.user_id if isinstance(participant.actor, UserActor) else None
        department_id = (
            participant.actor.department_id
            if isinstance(participant.actor, DepartmentActor)
            else None
        )
        self._session.add(
            FindingParticipantRecord(
                id=uuid4(),
                organization_id=participant.organization_id,
                finding_id=participant.finding_id,
                user_id=user_id,
                department_id=department_id,
                role_key=participant.role_key,
                assigned_at=participant.assigned_at,
            )
        )
        self._session.flush()

    def list_finding_participants(
        self,
        organization_id: OrganizationId,
        finding_id: FindingId,
    ) -> tuple[FindingParticipant, ...]:
        records = self._session.scalars(
            select(FindingParticipantRecord)
            .where(
                FindingParticipantRecord.organization_id == organization_id,
                FindingParticipantRecord.finding_id == finding_id,
            )
            .order_by(
                FindingParticipantRecord.assigned_at,
                FindingParticipantRecord.role_key,
                FindingParticipantRecord.id,
            )
        )
        return tuple(self._finding_participant_to_domain(record) for record in records)

    @staticmethod
    def _finding_participant_to_domain(
        record: FindingParticipantRecord,
    ) -> FindingParticipant:
        actor: ParticipantActor
        if record.user_id is not None:
            actor = UserActor(UserId(record.user_id))
        else:
            if record.department_id is None:
                raise ValueError("FindingParticipant has no actor")
            actor = DepartmentActor(DepartmentId(record.department_id))
        return FindingParticipant(
            organization_id=OrganizationId(record.organization_id),
            finding_id=FindingId(record.finding_id),
            actor=actor,
            role_key=record.role_key,
            assigned_at=record.assigned_at,
        )

    def add_action_item(self, action_item: ActionItem) -> None:
        self._session.add(
            ActionItemRecord(
                id=action_item.id,
                organization_id=action_item.organization_id,
                finding_id=action_item.finding_id,
                title=action_item.title,
                lifecycle=action_item.lifecycle.value,
                due_at=action_item.due_at,
            )
        )
        self._session.flush()

    def get_action_item(
        self,
        organization_id: OrganizationId,
        action_item_id: ActionItemId,
    ) -> ActionItem | None:
        record = self._session.scalar(
            select(ActionItemRecord).where(
                ActionItemRecord.organization_id == organization_id,
                ActionItemRecord.id == action_item_id,
            )
        )
        if record is None:
            return None
        return ActionItem(
            id=ActionItemId(record.id),
            organization_id=OrganizationId(record.organization_id),
            finding_id=FindingId(record.finding_id),
            title=record.title,
            lifecycle=ActionItemLifecycle(record.lifecycle),
            due_at=record.due_at,
        )

    def add_action_assignee(self, assignee: ActionAssignee) -> None:
        user_id = assignee.actor.user_id if isinstance(assignee.actor, UserActor) else None
        department_id = (
            assignee.actor.department_id if isinstance(assignee.actor, DepartmentActor) else None
        )
        self._session.add(
            ActionAssigneeRecord(
                id=uuid4(),
                organization_id=assignee.organization_id,
                action_item_id=assignee.action_item_id,
                user_id=user_id,
                department_id=department_id,
                role=assignee.role.value,
                assigned_at=assignee.assigned_at,
            )
        )
        self._session.flush()

    def add_submission(self, submission: Submission) -> None:
        self._session.add(
            SubmissionRecord(
                id=submission.id,
                organization_id=submission.organization_id,
                case_id=submission.case_id,
                finding_id=submission.finding_id,
                purpose=submission.purpose.value,
                submitted_by=submission.submitted_by,
                submitted_at=submission.submitted_at,
                payload_json=dict(submission.payload),
            )
        )
        self._session.flush()

    def get_submission(
        self,
        organization_id: OrganizationId,
        submission_id: SubmissionId,
    ) -> Submission | None:
        record = self._session.scalar(
            select(SubmissionRecord).where(
                SubmissionRecord.organization_id == organization_id,
                SubmissionRecord.id == submission_id,
            )
        )
        if record is None:
            return None
        return Submission(
            id=SubmissionId(record.id),
            organization_id=OrganizationId(record.organization_id),
            case_id=ReviewCaseId(record.case_id),
            finding_id=FindingId(record.finding_id) if record.finding_id is not None else None,
            purpose=SubmissionPurpose(record.purpose),
            submitted_by=UserId(record.submitted_by),
            submitted_at=record.submitted_at,
            payload=record.payload_json,
        )

    def add_activity(self, activity: Activity) -> None:
        targets: dict[str, object | None] = {
            "review_case_id": None,
            "finding_id": None,
            "action_item_id": None,
            "submission_id": None,
        }
        if isinstance(activity.subject, ReviewCaseActivitySubject):
            targets["review_case_id"] = activity.subject.review_case_id
        elif isinstance(activity.subject, FindingActivitySubject):
            targets["finding_id"] = activity.subject.finding_id
        elif isinstance(activity.subject, ActionItemActivitySubject):
            targets["action_item_id"] = activity.subject.action_item_id
        else:
            targets["submission_id"] = activity.subject.submission_id
        self._session.add(
            ActivityRecord(
                id=activity.id,
                organization_id=activity.organization_id,
                actor_id=activity.actor_id,
                event_type=activity.event_type,
                occurred_at=activity.occurred_at,
                metadata_json=dict(activity.metadata),
                **targets,
            )
        )
        self._session.flush()

    def get_activity(
        self,
        organization_id: OrganizationId,
        activity_id: ActivityId,
    ) -> Activity | None:
        record = self._session.scalar(
            select(ActivityRecord).where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.id == activity_id,
            )
        )
        if record is None:
            return None
        subject: ActivitySubject
        if record.review_case_id is not None:
            subject = ReviewCaseActivitySubject(ReviewCaseId(record.review_case_id))
        elif record.finding_id is not None:
            subject = FindingActivitySubject(FindingId(record.finding_id))
        elif record.action_item_id is not None:
            subject = ActionItemActivitySubject(ActionItemId(record.action_item_id))
        elif record.submission_id is not None:
            subject = SubmissionActivitySubject(SubmissionId(record.submission_id))
        else:
            raise LookupError("Activity has no typed target")
        return Activity(
            id=ActivityId(record.id),
            organization_id=OrganizationId(record.organization_id),
            subject=subject,
            event_type=record.event_type,
            actor_id=UserId(record.actor_id) if record.actor_id is not None else None,
            occurred_at=record.occurred_at,
            metadata=record.metadata_json,
        )
