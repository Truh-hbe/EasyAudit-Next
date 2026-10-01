from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from easyaudit_next.management.schemas import (
    ActionLifecycleCounts,
    DeadlineBucket,
    FindingLifecycleCounts,
    ManagementActionDeadlineItem,
    ManagementCaseCollectionResponse,
    ManagementCaseExportSnapshot,
    ManagementCaseFilters,
    ManagementCaseProgressResponse,
    ManagementCaseSummary,
    ManagementDeadlineFilter,
    ManagementFindingProgress,
)
from easyaudit_next.platform.domain.models import User
from easyaudit_next.platform.persistence.models import OrganizationRecord
from easyaudit_next.review_core.domain.models import (
    ActionItemLifecycle,
    FindingLifecycle,
    FindingSeverity,
    ReviewCaseLifecycle,
    ScenarioKey,
    ScenarioVersion,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActorKind,
    AuthorizationContext,
    PermissionSource,
    RoleGrant,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioPolicy, ScenarioRegistry
from easyaudit_next.review_core.persistence.models import (
    ActionAssigneeRecord,
    ActionItemRecord,
    CaseMemberRecord,
    FindingParticipantRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)

MANAGE_CASE_MEMBERS_PERMISSION = "manage_case_members"
VIEW_CASE_PERMISSION = "view_case"
VIEW_FINDING_PERMISSION = "view_finding"
_DUE_SOON_WINDOW = timedelta(days=7)
_CASE_DEADLINE_LIFECYCLES = {
    ReviewCaseLifecycle.SCHEDULED,
    ReviewCaseLifecycle.IN_PROGRESS,
}
_ACTION_DEADLINE_LIFECYCLES = {
    ActionItemLifecycle.TODO,
    ActionItemLifecycle.IN_PROGRESS,
}


class ExportRowLimitExceededError(Exception):
    def __init__(self, max_rows: int) -> None:
        super().__init__("Export exceeds the row limit")
        self.max_rows = max_rows


class ManagementQueryService:
    """Authorization-safe M3.3 management projection over existing Review facts."""

    def __init__(self, session: Session, registry: ScenarioRegistry) -> None:
        self._session = session
        self._registry = registry

    def list_review_cases(
        self,
        actor: User,
        *,
        review_plan_id: UUID | None = None,
        lifecycle: ReviewCaseLifecycle | None = None,
        deadline_status: ManagementDeadlineFilter = ManagementDeadlineFilter.ALL,
        limit: int = 50,
        offset: int = 0,
        as_of: datetime | None = None,
    ) -> ManagementCaseCollectionResponse:
        captured_at = self._capture_as_of(actor, as_of)
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if offset < 0:
            raise ValueError("offset must be non-negative")

        summaries = self._filtered_summaries(
            actor,
            captured_at,
            review_plan_id=review_plan_id,
            lifecycle=lifecycle,
            deadline_status=deadline_status,
        )
        total = len(summaries)
        page = tuple(summaries[offset : offset + limit])
        return ManagementCaseCollectionResponse(
            as_of=captured_at,
            items=page,
            total=total,
            limit=limit,
            offset=offset,
        )

    def export_review_cases(
        self,
        actor: User,
        filters: ManagementCaseFilters,
        *,
        max_rows: int,
        as_of: datetime | None = None,
    ) -> ManagementCaseExportSnapshot:
        """All rows of `list_review_cases` for the same filters, without pagination.

        Fails as a whole when the filtered row count exceeds `max_rows`; never truncates.
        """
        captured_at = self._capture_as_of(actor, as_of)
        summaries = self._filtered_summaries(
            actor,
            captured_at,
            review_plan_id=filters.review_plan_id,
            lifecycle=filters.lifecycle,
            deadline_status=filters.deadline_status,
        )
        if len(summaries) > max_rows:
            raise ExportRowLimitExceededError(max_rows)
        organization_name = self._session.scalar(
            select(OrganizationRecord.name).where(OrganizationRecord.id == actor.organization_id)
        )
        if organization_name is None:
            raise LookupError("Organization not found for management export")
        return ManagementCaseExportSnapshot(
            as_of=captured_at,
            organization_name=organization_name,
            filters=filters,
            items=tuple(summaries),
        )

    def _filtered_summaries(
        self,
        actor: User,
        as_of: datetime,
        *,
        review_plan_id: UUID | None,
        lifecycle: ReviewCaseLifecycle | None,
        deadline_status: ManagementDeadlineFilter,
    ) -> list[ManagementCaseSummary]:
        """Authorized snapshot -> filters -> sort. The single source for every case listing."""
        summaries = list(self._authorized_snapshot(actor, as_of).summaries)

        if review_plan_id is not None:
            summaries = [item for item in summaries if item.review_plan_id == review_plan_id]
        if lifecycle is not None:
            summaries = [item for item in summaries if item.lifecycle is lifecycle]
        if deadline_status is ManagementDeadlineFilter.OVERDUE:
            summaries = [
                item for item in summaries if item.deadline_bucket is DeadlineBucket.OVERDUE
            ]
        elif deadline_status is ManagementDeadlineFilter.DUE_SOON:
            summaries = [
                item for item in summaries if item.deadline_bucket is DeadlineBucket.DUE_SOON
            ]

        summaries.sort(key=self._case_sort_key)
        return summaries

    def get_progress(
        self,
        actor: User,
        case_id: UUID,
        *,
        as_of: datetime | None = None,
    ) -> ManagementCaseProgressResponse:
        captured_at = self._capture_as_of(actor, as_of)
        snapshot = self._authorized_snapshot(actor, captured_at, case_id=case_id)
        if not snapshot.summaries:
            raise LookupError("Managed ReviewCase not found")
        summary = snapshot.summaries[0]
        return ManagementCaseProgressResponse(
            as_of=captured_at,
            case=summary,
            findings=snapshot.finding_progress.get(summary.id, ()),
            overdue_actions=snapshot.overdue_actions.get(summary.id, ()),
            due_soon_actions=snapshot.due_soon_actions.get(summary.id, ()),
        )

    def _authorized_snapshot(
        self,
        actor: User,
        as_of: datetime,
        *,
        case_id: UUID | None = None,
    ) -> "_ManagementSnapshot":
        candidate_members = self._load_candidate_members(actor, case_id)
        candidate_case_ids = {member.case_id for member in candidate_members}
        if not candidate_case_ids:
            return _ManagementSnapshot.empty()

        cases = self._load_cases(actor, candidate_case_ids)
        versions = self._load_scenario_versions(actor, cases)
        version_by_id = {record.id: record for record in versions}
        scenarios = self._load_scenarios(actor, versions)
        scenario_by_id = {record.id: record for record in scenarios}

        findings = self._load_findings(actor, candidate_case_ids)
        finding_by_id = {record.id: record for record in findings}
        actions = self._load_actions(actor, {record.id for record in findings})

        finding_participants = self._load_finding_participants(
            actor,
            {record.id for record in findings},
        )
        action_assignees = self._load_action_assignees(
            actor,
            {record.id for record in actions},
        )

        case_grants: dict[UUID, set[RoleGrant]] = defaultdict(set)
        for member in candidate_members:
            case_grants[member.case_id].add(
                RoleGrant(
                    role_key=member.role_key,
                    actor_kind=ActorKind.USER,
                    source=PermissionSource.DIRECT,
                )
            )

        finding_grants: dict[UUID, set[RoleGrant]] = defaultdict(set)
        for participant in finding_participants:
            finding_grants[participant.finding_id].add(self._participant_grant(participant))

        action_grants: dict[UUID, set[RoleGrant]] = defaultdict(set)
        for assignee in action_assignees:
            action_grants[assignee.action_item_id].add(self._assignee_grant(assignee))

        finding_grants_by_case: dict[UUID, set[RoleGrant]] = defaultdict(set)
        for finding in findings:
            finding_grants_by_case[finding.case_id].update(finding_grants.get(finding.id, set()))

        action_grants_by_finding: dict[UUID, set[RoleGrant]] = defaultdict(set)
        action_grants_by_case: dict[UUID, set[RoleGrant]] = defaultdict(set)
        for action in actions:
            grants = action_grants.get(action.id, set())
            action_grants_by_finding[action.finding_id].update(grants)
            parent = finding_by_id.get(action.finding_id)
            if parent is not None:
                action_grants_by_case[parent.case_id].update(grants)

        def policy_for_case(review_case: ReviewCaseRecord) -> ScenarioPolicy:
            version = version_by_id.get(review_case.scenario_version_id)
            if version is None:
                raise LookupError("Scenario version not found for management ReviewCase")
            scenario = scenario_by_id.get(version.scenario_id)
            if scenario is None:
                raise LookupError("Scenario not found for management ReviewCase")
            return self._registry.get(
                ScenarioKey(scenario.key),
                ScenarioVersion(version.version),
            )

        def case_context(case_uuid: UUID) -> AuthorizationContext:
            return AuthorizationContext(
                is_active_organization_user=actor.is_active,
                case_role_grants=frozenset(case_grants.get(case_uuid, set())),
                finding_role_grants=frozenset(finding_grants_by_case.get(case_uuid, set())),
                action_role_grants=frozenset(action_grants_by_case.get(case_uuid, set())),
            )

        def finding_context(finding: FindingRecord) -> AuthorizationContext:
            return AuthorizationContext(
                is_active_organization_user=actor.is_active,
                case_role_grants=frozenset(case_grants.get(finding.case_id, set())),
                finding_role_grants=frozenset(finding_grants.get(finding.id, set())),
                action_role_grants=frozenset(action_grants_by_finding.get(finding.id, set())),
            )

        authorized_cases: list[ReviewCaseRecord] = []
        policy_by_case: dict[UUID, ScenarioPolicy] = {}
        for review_case in cases:
            policy = policy_for_case(review_case)
            context = case_context(review_case.id)
            if not policy.authorization.allows(MANAGE_CASE_MEMBERS_PERMISSION, context):
                continue
            if not policy.authorization.allows(VIEW_CASE_PERMISSION, context):
                continue
            authorized_cases.append(review_case)
            policy_by_case[review_case.id] = policy

        if not authorized_cases:
            return _ManagementSnapshot.empty()

        authorized_case_ids = {record.id for record in authorized_cases}
        visible_findings_by_case: dict[UUID, list[FindingRecord]] = defaultdict(list)
        for finding in findings:
            if finding.case_id not in authorized_case_ids:
                continue
            policy = policy_by_case[finding.case_id]
            if policy.authorization.allows(VIEW_FINDING_PERMISSION, finding_context(finding)):
                visible_findings_by_case[finding.case_id].append(finding)

        visible_finding_ids = {
            finding.id
            for case_findings in visible_findings_by_case.values()
            for finding in case_findings
        }
        visible_actions_by_finding: dict[UUID, list[ActionItemRecord]] = defaultdict(list)
        for action in actions:
            if action.finding_id in visible_finding_ids:
                visible_actions_by_finding[action.finding_id].append(action)

        summaries: list[ManagementCaseSummary] = []
        finding_progress: dict[UUID, tuple[ManagementFindingProgress, ...]] = {}
        overdue_actions: dict[UUID, tuple[ManagementActionDeadlineItem, ...]] = {}
        due_soon_actions: dict[UUID, tuple[ManagementActionDeadlineItem, ...]] = {}

        for review_case in authorized_cases:
            version = version_by_id[review_case.scenario_version_id]
            scenario = scenario_by_id[version.scenario_id]
            case_findings = sorted(
                visible_findings_by_case.get(review_case.id, []),
                key=lambda item: (item.raised_at, str(item.id)),
            )
            all_case_actions = [
                action
                for finding in case_findings
                for action in visible_actions_by_finding.get(finding.id, [])
            ]
            summary = ManagementCaseSummary(
                id=review_case.id,
                review_plan_id=review_case.plan_id,
                title=review_case.title,
                scenario_key=scenario.key,
                scenario_version=version.version,
                lifecycle=ReviewCaseLifecycle(review_case.lifecycle),
                planned_start_at=review_case.planned_start_at,
                planned_end_at=review_case.planned_end_at,
                deadline_bucket=self._case_deadline_bucket(review_case, as_of),
                findings=self._finding_counts(case_findings),
                actions=self._action_counts(all_case_actions, as_of),
            )
            summaries.append(summary)

            finding_progress[review_case.id] = tuple(
                ManagementFindingProgress(
                    id=finding.id,
                    title=finding.title,
                    severity=FindingSeverity(finding.severity),
                    lifecycle=FindingLifecycle(finding.lifecycle),
                    raised_at=finding.raised_at,
                    actions=self._action_counts(
                        visible_actions_by_finding.get(finding.id, []),
                        as_of,
                    ),
                )
                for finding in case_findings
            )

            overdue = [
                self._deadline_item(action)
                for action in all_case_actions
                if self._action_deadline_bucket(action, as_of) is DeadlineBucket.OVERDUE
            ]
            due_soon = [
                self._deadline_item(action)
                for action in all_case_actions
                if self._action_deadline_bucket(action, as_of) is DeadlineBucket.DUE_SOON
            ]
            overdue.sort(key=lambda item: (item.due_at, str(item.id)))
            due_soon.sort(key=lambda item: (item.due_at, str(item.id)))
            overdue_actions[review_case.id] = tuple(overdue)
            due_soon_actions[review_case.id] = tuple(due_soon)

        return _ManagementSnapshot(
            summaries=tuple(summaries),
            finding_progress=finding_progress,
            overdue_actions=overdue_actions,
            due_soon_actions=due_soon_actions,
        )

    @staticmethod
    def _capture_as_of(actor: User, as_of: datetime | None) -> datetime:
        if not actor.is_active:
            raise PermissionError("Active organization user required")
        captured_at = as_of or datetime.now(UTC)
        if captured_at.utcoffset() is None:
            raise ValueError("as_of must include UTC offset")
        return captured_at

    def _load_candidate_members(
        self,
        actor: User,
        case_id: UUID | None,
    ) -> tuple[CaseMemberRecord, ...]:
        statement = select(CaseMemberRecord).where(
            CaseMemberRecord.organization_id == actor.organization_id,
            CaseMemberRecord.user_id == actor.id,
        )
        if case_id is not None:
            statement = statement.where(CaseMemberRecord.case_id == case_id)
        return tuple(self._session.scalars(statement))

    def _load_cases(self, actor: User, case_ids: set[UUID]) -> tuple[ReviewCaseRecord, ...]:
        if not case_ids:
            return ()
        return tuple(
            self._session.scalars(
                select(ReviewCaseRecord).where(
                    ReviewCaseRecord.organization_id == actor.organization_id,
                    ReviewCaseRecord.id.in_(case_ids),
                )
            )
        )

    def _load_scenario_versions(
        self,
        actor: User,
        cases: tuple[ReviewCaseRecord, ...],
    ) -> tuple[ScenarioVersionRecord, ...]:
        ids = {record.scenario_version_id for record in cases}
        if not ids:
            return ()
        return tuple(
            self._session.scalars(
                select(ScenarioVersionRecord).where(
                    ScenarioVersionRecord.organization_id == actor.organization_id,
                    ScenarioVersionRecord.id.in_(ids),
                )
            )
        )

    def _load_scenarios(
        self,
        actor: User,
        versions: tuple[ScenarioVersionRecord, ...],
    ) -> tuple[ScenarioRecord, ...]:
        ids = {record.scenario_id for record in versions}
        if not ids:
            return ()
        return tuple(
            self._session.scalars(
                select(ScenarioRecord).where(
                    ScenarioRecord.organization_id == actor.organization_id,
                    ScenarioRecord.id.in_(ids),
                )
            )
        )

    def _load_findings(self, actor: User, case_ids: set[UUID]) -> tuple[FindingRecord, ...]:
        if not case_ids:
            return ()
        return tuple(
            self._session.scalars(
                select(FindingRecord).where(
                    FindingRecord.organization_id == actor.organization_id,
                    FindingRecord.case_id.in_(case_ids),
                )
            )
        )

    def _load_actions(self, actor: User, finding_ids: set[UUID]) -> tuple[ActionItemRecord, ...]:
        if not finding_ids:
            return ()
        return tuple(
            self._session.scalars(
                select(ActionItemRecord).where(
                    ActionItemRecord.organization_id == actor.organization_id,
                    ActionItemRecord.finding_id.in_(finding_ids),
                )
            )
        )

    def _load_finding_participants(
        self,
        actor: User,
        finding_ids: set[UUID],
    ) -> tuple[FindingParticipantRecord, ...]:
        if not finding_ids:
            return ()
        actor_filter = FindingParticipantRecord.user_id == actor.id
        if actor.primary_department_id is not None:
            actor_filter = or_(
                actor_filter,
                FindingParticipantRecord.department_id == actor.primary_department_id,
            )
        return tuple(
            self._session.scalars(
                select(FindingParticipantRecord).where(
                    FindingParticipantRecord.organization_id == actor.organization_id,
                    FindingParticipantRecord.finding_id.in_(finding_ids),
                    actor_filter,
                )
            )
        )

    def _load_action_assignees(
        self,
        actor: User,
        action_ids: set[UUID],
    ) -> tuple[ActionAssigneeRecord, ...]:
        if not action_ids:
            return ()
        actor_filter = ActionAssigneeRecord.user_id == actor.id
        if actor.primary_department_id is not None:
            actor_filter = or_(
                actor_filter,
                ActionAssigneeRecord.department_id == actor.primary_department_id,
            )
        return tuple(
            self._session.scalars(
                select(ActionAssigneeRecord).where(
                    ActionAssigneeRecord.organization_id == actor.organization_id,
                    ActionAssigneeRecord.action_item_id.in_(action_ids),
                    actor_filter,
                )
            )
        )

    @staticmethod
    def _participant_grant(record: FindingParticipantRecord) -> RoleGrant:
        if record.user_id is not None:
            return RoleGrant(
                role_key=record.role_key,
                actor_kind=ActorKind.USER,
                source=PermissionSource.DIRECT,
            )
        return RoleGrant(
            role_key=record.role_key,
            actor_kind=ActorKind.DEPARTMENT,
            source=PermissionSource.DEPARTMENT_MEMBERSHIP,
        )

    @staticmethod
    def _assignee_grant(record: ActionAssigneeRecord) -> RoleGrant:
        if record.user_id is not None:
            return RoleGrant(
                role_key=record.role,
                actor_kind=ActorKind.USER,
                source=PermissionSource.DIRECT,
            )
        return RoleGrant(
            role_key=record.role,
            actor_kind=ActorKind.DEPARTMENT,
            source=PermissionSource.DEPARTMENT_MEMBERSHIP,
        )

    @staticmethod
    def _case_deadline_bucket(record: ReviewCaseRecord, as_of: datetime) -> DeadlineBucket:
        if record.planned_end_at is None:
            return DeadlineBucket.NONE
        lifecycle = ReviewCaseLifecycle(record.lifecycle)
        if lifecycle not in _CASE_DEADLINE_LIFECYCLES:
            return DeadlineBucket.NONE
        if record.planned_end_at < as_of:
            return DeadlineBucket.OVERDUE
        if record.planned_end_at <= as_of + _DUE_SOON_WINDOW:
            return DeadlineBucket.DUE_SOON
        return DeadlineBucket.LATER

    @staticmethod
    def _action_deadline_bucket(record: ActionItemRecord, as_of: datetime) -> DeadlineBucket:
        if record.due_at is None:
            return DeadlineBucket.NONE
        lifecycle = ActionItemLifecycle(record.lifecycle)
        if lifecycle not in _ACTION_DEADLINE_LIFECYCLES:
            return DeadlineBucket.NONE
        if record.due_at < as_of:
            return DeadlineBucket.OVERDUE
        if record.due_at <= as_of + _DUE_SOON_WINDOW:
            return DeadlineBucket.DUE_SOON
        return DeadlineBucket.LATER

    @staticmethod
    def _finding_counts(records: list[FindingRecord]) -> FindingLifecycleCounts:
        counts = {lifecycle: 0 for lifecycle in FindingLifecycle}
        for record in records:
            counts[FindingLifecycle(record.lifecycle)] += 1
        return FindingLifecycleCounts(
            total=len(records),
            open=counts[FindingLifecycle.OPEN],
            rectifying=counts[FindingLifecycle.RECTIFYING],
            verifying=counts[FindingLifecycle.VERIFYING],
            closed=counts[FindingLifecycle.CLOSED],
            voided=counts[FindingLifecycle.VOIDED],
        )

    def _action_counts(
        self,
        records: list[ActionItemRecord],
        as_of: datetime,
    ) -> ActionLifecycleCounts:
        counts = {lifecycle: 0 for lifecycle in ActionItemLifecycle}
        overdue = 0
        due_soon = 0
        for record in records:
            counts[ActionItemLifecycle(record.lifecycle)] += 1
            bucket = self._action_deadline_bucket(record, as_of)
            if bucket is DeadlineBucket.OVERDUE:
                overdue += 1
            elif bucket is DeadlineBucket.DUE_SOON:
                due_soon += 1
        return ActionLifecycleCounts(
            total=len(records),
            todo=counts[ActionItemLifecycle.TODO],
            in_progress=counts[ActionItemLifecycle.IN_PROGRESS],
            done=counts[ActionItemLifecycle.DONE],
            cancelled=counts[ActionItemLifecycle.CANCELLED],
            overdue=overdue,
            due_soon=due_soon,
        )

    @staticmethod
    def _deadline_item(record: ActionItemRecord) -> ManagementActionDeadlineItem:
        assert record.due_at is not None
        return ManagementActionDeadlineItem(
            id=record.id,
            title=record.title,
            lifecycle=ActionItemLifecycle(record.lifecycle),
            due_at=record.due_at,
        )

    @staticmethod
    def _case_sort_key(
        item: ManagementCaseSummary,
    ) -> tuple[int, bool, datetime, str]:
        return (
            0 if item.deadline_bucket is DeadlineBucket.OVERDUE else 1,
            item.planned_end_at is None,
            item.planned_end_at or datetime.max.replace(tzinfo=UTC),
            str(item.id),
        )


class _ManagementSnapshot:
    def __init__(
        self,
        *,
        summaries: tuple[ManagementCaseSummary, ...],
        finding_progress: dict[UUID, tuple[ManagementFindingProgress, ...]],
        overdue_actions: dict[UUID, tuple[ManagementActionDeadlineItem, ...]],
        due_soon_actions: dict[UUID, tuple[ManagementActionDeadlineItem, ...]],
    ) -> None:
        self.summaries = summaries
        self.finding_progress = finding_progress
        self.overdue_actions = overdue_actions
        self.due_soon_actions = due_soon_actions

    @classmethod
    def empty(cls) -> "_ManagementSnapshot":
        return cls(
            summaries=(),
            finding_progress={},
            overdue_actions={},
            due_soon_actions={},
        )
