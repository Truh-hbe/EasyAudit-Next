from sqlalchemy import select, update

from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.review_core.domain.ids import (
    ActionItemId,
    EvidenceId,
    FindingId,
    ReviewCaseId,
    SubmissionId,
)
from easyaudit_next.review_core.domain.models import (
    ActionAssignee,
    ActionItem,
    ActionItemLifecycle,
    AssignmentRole,
    DepartmentActor,
    Evidence,
    Finding,
    ParticipantActor,
    Submission,
    SubmissionPurpose,
    UserActor,
)
from easyaudit_next.review_core.persistence.models import (
    ActionAssigneeRecord,
    ActionItemRecord,
    EvidenceRecord,
    FindingRecord,
    SubmissionRecord,
)
from easyaudit_next.review_core.persistence.repositories import (
    SqlAlchemyReviewCoreRepository,
)


class SqlAlchemyRectificationRepository(SqlAlchemyReviewCoreRepository):
    """Review Core persistence with the M2.4 rectification surface."""

    def lock_finding_for_rectification(
        self,
        organization_id: OrganizationId,
        finding_id: FindingId,
    ) -> Finding | None:
        record = self._session.scalar(
            select(FindingRecord)
            .where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.id == finding_id,
            )
            .with_for_update()
        )
        return self._finding_to_domain(record) if record is not None else None

    def add_action_item(self, action_item: ActionItem) -> None:
        self._session.add(
            ActionItemRecord(
                id=action_item.id,
                organization_id=action_item.organization_id,
                finding_id=action_item.finding_id,
                title=action_item.title,
                lifecycle=action_item.lifecycle.value,
                due_at=action_item.due_at,
                completed_at=action_item.completed_at,
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
        return self._action_to_domain(record) if record is not None else None

    def list_action_items(
        self,
        organization_id: OrganizationId,
        finding_id: FindingId,
    ) -> tuple[ActionItem, ...]:
        records = self._session.scalars(
            select(ActionItemRecord)
            .where(
                ActionItemRecord.organization_id == organization_id,
                ActionItemRecord.finding_id == finding_id,
            )
            .order_by(ActionItemRecord.due_at, ActionItemRecord.id)
        )
        return tuple(self._action_to_domain(record) for record in records)

    def update_action_item(
        self,
        action_item: ActionItem,
        *,
        expected_lifecycle: ActionItemLifecycle,
    ) -> bool:
        matched_id: object | None = self._session.scalar(
            update(ActionItemRecord)
            .where(
                ActionItemRecord.organization_id == action_item.organization_id,
                ActionItemRecord.id == action_item.id,
                ActionItemRecord.lifecycle == expected_lifecycle.value,
            )
            .values(
                lifecycle=action_item.lifecycle.value,
                completed_at=action_item.completed_at,
            )
            .returning(ActionItemRecord.id)
            .execution_options(synchronize_session="fetch")
        )
        self._session.flush()
        return matched_id is not None

    def list_action_assignees(
        self,
        organization_id: OrganizationId,
        action_item_id: ActionItemId,
    ) -> tuple[ActionAssignee, ...]:
        records = self._session.scalars(
            select(ActionAssigneeRecord)
            .where(
                ActionAssigneeRecord.organization_id == organization_id,
                ActionAssigneeRecord.action_item_id == action_item_id,
            )
            .order_by(ActionAssigneeRecord.assigned_at, ActionAssigneeRecord.role)
        )
        return tuple(self._assignee_to_domain(record) for record in records)

    def add_evidence(self, evidence: Evidence) -> None:
        self._session.add(
            EvidenceRecord(
                id=evidence.id,
                organization_id=evidence.organization_id,
                action_item_id=evidence.action_item_id,
                storage_key=evidence.storage_key,
                original_name=evidence.original_name,
                content_type=evidence.content_type,
                size_bytes=evidence.size_bytes,
                sha256=evidence.sha256,
                description=evidence.description,
                uploaded_by=evidence.uploaded_by,
                created_at=evidence.created_at,
            )
        )
        self._session.flush()

    def get_evidence(
        self,
        organization_id: OrganizationId,
        evidence_id: EvidenceId,
    ) -> Evidence | None:
        record = self._session.scalar(
            select(EvidenceRecord).where(
                EvidenceRecord.organization_id == organization_id,
                EvidenceRecord.id == evidence_id,
            )
        )
        return self._evidence_to_domain(record) if record is not None else None

    def list_evidences(
        self,
        organization_id: OrganizationId,
        action_item_id: ActionItemId,
    ) -> tuple[Evidence, ...]:
        records = self._session.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.organization_id == organization_id,
                EvidenceRecord.action_item_id == action_item_id,
            )
            .order_by(EvidenceRecord.created_at, EvidenceRecord.id)
        )
        return tuple(self._evidence_to_domain(record) for record in records)

    def list_submissions(
        self,
        organization_id: OrganizationId,
        finding_id: FindingId,
    ) -> tuple[Submission, ...]:
        records = self._session.scalars(
            select(SubmissionRecord)
            .where(
                SubmissionRecord.organization_id == organization_id,
                SubmissionRecord.finding_id == finding_id,
            )
            .order_by(SubmissionRecord.submitted_at, SubmissionRecord.id)
        )
        return tuple(
            Submission(
                id=SubmissionId(record.id),
                organization_id=OrganizationId(record.organization_id),
                case_id=ReviewCaseId(record.case_id),
                finding_id=FindingId(record.finding_id) if record.finding_id is not None else None,
                purpose=SubmissionPurpose(record.purpose),
                submitted_by=UserId(record.submitted_by),
                submitted_at=record.submitted_at,
                payload=record.payload_json,
            )
            for record in records
        )

    @staticmethod
    def _action_to_domain(record: ActionItemRecord) -> ActionItem:
        return ActionItem(
            id=ActionItemId(record.id),
            organization_id=OrganizationId(record.organization_id),
            finding_id=FindingId(record.finding_id),
            title=record.title,
            lifecycle=ActionItemLifecycle(record.lifecycle),
            due_at=record.due_at,
            completed_at=record.completed_at,
        )

    @staticmethod
    def _assignee_to_domain(record: ActionAssigneeRecord) -> ActionAssignee:
        actor: ParticipantActor
        if record.user_id is not None:
            actor = UserActor(UserId(record.user_id))
        else:
            if record.department_id is None:
                raise ValueError("ActionAssignee has no actor")
            actor = DepartmentActor(DepartmentId(record.department_id))
        return ActionAssignee(
            organization_id=OrganizationId(record.organization_id),
            action_item_id=ActionItemId(record.action_item_id),
            actor=actor,
            role=AssignmentRole(record.role),
            assigned_at=record.assigned_at,
        )

    @staticmethod
    def _evidence_to_domain(record: EvidenceRecord) -> Evidence:
        return Evidence(
            id=EvidenceId(record.id),
            organization_id=OrganizationId(record.organization_id),
            action_item_id=ActionItemId(record.action_item_id),
            storage_key=record.storage_key,
            original_name=record.original_name,
            content_type=record.content_type,
            size_bytes=record.size_bytes,
            sha256=record.sha256,
            description=record.description,
            uploaded_by=UserId(record.uploaded_by),
            created_at=record.created_at,
        )
