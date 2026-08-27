from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from easyaudit_next.platform.domain.models import User
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
from easyaudit_next.workbench.schemas import (
    WorkbenchActionDeadline,
    WorkbenchActionResponsibility,
    WorkbenchCaseDeadline,
    WorkbenchCaseResponsibility,
    WorkbenchDeadlineBucket,
    WorkbenchFindingResponsibility,
    WorkbenchRelationship,
    WorkbenchResponse,
    WorkbenchVerificationItem,
)

VIEW_CASE_PERMISSION = "view_case"
VIEW_FINDING_PERMISSION = "view_finding"
VERIFY_FINDING_PERMISSION = "verify_finding"
_DUE_SOON_WINDOW = timedelta(days=7)
_CASE_DEADLINE_LIFECYCLES = {
    ReviewCaseLifecycle.SCHEDULED,
    ReviewCaseLifecycle.IN_PROGRESS,
}
_ACTION_DEADLINE_LIFECYCLES = {
    ActionItemLifecycle.TODO,
    ActionItemLifecycle.IN_PROGRESS,
}

RelationshipKey = tuple[str, ActorKind, PermissionSource]


class WorkbenchQueryService:
    """Read-side projection over M2 facts without widening authorization scope."""

    def __init__(self, session: Session, registry: ScenarioRegistry) -> None:
        self._session = session
        self._registry = registry

    def get_workbench(
        self,
        actor: User,
        *,
        as_of: datetime | None = None,
    ) -> WorkbenchResponse:
        if not actor.is_active:
            raise PermissionError("Active organization user required")
        captured_at = as_of or datetime.now(UTC)
        if captured_at.utcoffset() is None:
            raise ValueError("as_of must include UTC offset")

        case_members = self._load_case_members(actor)
        finding_participants = self._load_finding_participants(actor)
        action_assignees = self._load_action_assignees(actor)

        assigned_action_ids = {
            assignee.action_item_id for assignee in action_assignees
        }
        actions = self._load_actions(actor, assigned_action_ids)
        action_by_id = {action.id: action for action in actions}

        relationship_finding_ids = {
            participant.finding_id for participant in finding_participants
        }
        relationship_finding_ids.update(action.finding_id for action in actions)
        findings = self._load_findings(actor, relationship_finding_ids)
        finding_by_id = {finding.id: finding for finding in findings}

        case_ids = {case_member.case_id for case_member in case_members}
        case_ids.update(finding.case_id for finding in findings)
        cases = self._load_cases(actor, case_ids)
        case_by_id = {review_case.id: review_case for review_case in cases}

        versions = self._load_scenario_versions(actor, cases)
        version_by_id = {version.id: version for version in versions}
        scenarios = self._load_scenarios(actor, versions)
        scenario_by_id = {scenario.id: scenario for scenario in scenarios}

        case_grants: dict[UUID, set[RoleGrant]] = defaultdict(set)
        case_role_keys: dict[UUID, set[str]] = defaultdict(set)
        for case_member in case_members:
            case_grants[case_member.case_id].add(
                RoleGrant(
                    role_key=case_member.role_key,
                    actor_kind=ActorKind.USER,
                    source=PermissionSource.DIRECT,
                )
            )
            case_role_keys[case_member.case_id].add(case_member.role_key)

        finding_grants: dict[UUID, set[RoleGrant]] = defaultdict(set)
        finding_relationships: dict[UUID, set[RelationshipKey]] = defaultdict(set)
        for participant in finding_participants:
            grant, relationship = self._participant_fact(participant)
            finding_grants[participant.finding_id].add(grant)
            finding_relationships[participant.finding_id].add(relationship)

        action_grants: dict[UUID, set[RoleGrant]] = defaultdict(set)
        action_relationships: dict[UUID, set[RelationshipKey]] = defaultdict(set)
        for assignee in action_assignees:
            grant, relationship = self._assignee_fact(assignee)
            action_grants[assignee.action_item_id].add(grant)
            action_relationships[assignee.action_item_id].add(relationship)

        finding_grants_by_case: dict[UUID, set[RoleGrant]] = defaultdict(set)
        for finding_id, grants in finding_grants.items():
            finding = finding_by_id.get(finding_id)
            if finding is not None:
                finding_grants_by_case[finding.case_id].update(grants)

        action_grants_by_finding: dict[UUID, set[RoleGrant]] = defaultdict(set)
        action_grants_by_case: dict[UUID, set[RoleGrant]] = defaultdict(set)
        for action_id, grants in action_grants.items():
            action = action_by_id.get(action_id)
            if action is None:
                continue
            action_grants_by_finding[action.finding_id].update(grants)
            finding = finding_by_id.get(action.finding_id)
            if finding is not None:
                action_grants_by_case[finding.case_id].update(grants)

        def policy_for_case(review_case: ReviewCaseRecord) -> ScenarioPolicy:
            version = version_by_id.get(review_case.scenario_version_id)
            if version is None:
                raise LookupError("Scenario version not found for Workbench ReviewCase")
            scenario = scenario_by_id.get(version.scenario_id)
            if scenario is None:
                raise LookupError("Scenario not found for Workbench ReviewCase")
            return self._registry.get(
                ScenarioKey(scenario.key),
                ScenarioVersion(version.version),
            )

        def case_context(case_id: UUID) -> AuthorizationContext:
            return AuthorizationContext(
                is_active_organization_user=actor.is_active,
                case_role_grants=frozenset(case_grants.get(case_id, set())),
                finding_role_grants=frozenset(finding_grants_by_case.get(case_id, set())),
                action_role_grants=frozenset(action_grants_by_case.get(case_id, set())),
            )

        def finding_context(finding: FindingRecord) -> AuthorizationContext:
            return AuthorizationContext(
                is_active_organization_user=actor.is_active,
                case_role_grants=frozenset(case_grants.get(finding.case_id, set())),
                finding_role_grants=frozenset(finding_grants.get(finding.id, set())),
                action_role_grants=frozenset(
                    action_grants_by_finding.get(finding.id, set())
                ),
            )

        def action_context(
            action: ActionItemRecord,
            finding: FindingRecord,
        ) -> AuthorizationContext:
            return AuthorizationContext(
                is_active_organization_user=actor.is_active,
                case_role_grants=frozenset(case_grants.get(finding.case_id, set())),
                finding_role_grants=frozenset(finding_grants.get(finding.id, set())),
                action_role_grants=frozenset(action_grants.get(action.id, set())),
            )

        case_responsibilities: list[WorkbenchCaseResponsibility] = []
        for case_id, roles in case_role_keys.items():
            review_case = case_by_id.get(case_id)
            if review_case is None:
                continue
            policy = policy_for_case(review_case)
            if not policy.authorization.allows(VIEW_CASE_PERMISSION, case_context(case_id)):
                continue
            case_responsibilities.append(
                WorkbenchCaseResponsibility(
                    id=review_case.id,
                    title=review_case.title,
                    lifecycle=ReviewCaseLifecycle(review_case.lifecycle),
                    role_keys=tuple(sorted(roles)),
                    planned_end_at=review_case.planned_end_at,
                )
            )

        finding_responsibilities: list[WorkbenchFindingResponsibility] = []
        for finding_id, relationships in finding_relationships.items():
            finding = finding_by_id.get(finding_id)
            if finding is None:
                continue
            review_case = case_by_id.get(finding.case_id)
            if review_case is None:
                continue
            policy = policy_for_case(review_case)
            if not policy.authorization.allows(
                VIEW_FINDING_PERMISSION,
                finding_context(finding),
            ):
                continue
            finding_responsibilities.append(
                WorkbenchFindingResponsibility(
                    id=finding.id,
                    case_id=finding.case_id,
                    title=finding.title,
                    severity=FindingSeverity(finding.severity),
                    lifecycle=FindingLifecycle(finding.lifecycle),
                    relationships=self._relationship_models(relationships),
                    raised_at=finding.raised_at,
                )
            )

        action_responsibilities: list[WorkbenchActionResponsibility] = []
        for action_id, relationships in action_relationships.items():
            action = action_by_id.get(action_id)
            if action is None:
                continue
            finding = finding_by_id.get(action.finding_id)
            if finding is None:
                continue
            review_case = case_by_id.get(finding.case_id)
            if review_case is None:
                continue
            policy = policy_for_case(review_case)
            if not policy.authorization.allows(
                VIEW_FINDING_PERMISSION,
                action_context(action, finding),
            ):
                continue
            action_responsibilities.append(
                WorkbenchActionResponsibility(
                    id=action.id,
                    finding_id=finding.id,
                    case_id=finding.case_id,
                    title=action.title,
                    lifecycle=ActionItemLifecycle(action.lifecycle),
                    due_at=action.due_at,
                    relationships=self._relationship_models(relationships),
                )
            )

        verification_queue: list[WorkbenchVerificationItem] = []
        for finding in findings:
            if finding.lifecycle != FindingLifecycle.VERIFYING.value:
                continue
            review_case = case_by_id.get(finding.case_id)
            if review_case is None:
                continue
            policy = policy_for_case(review_case)
            if not policy.authorization.allows(
                VERIFY_FINDING_PERMISSION,
                finding_context(finding),
            ):
                continue
            verification_queue.append(
                WorkbenchVerificationItem(
                    id=finding.id,
                    case_id=finding.case_id,
                    title=finding.title,
                    severity=FindingSeverity(finding.severity),
                    raised_at=finding.raised_at,
                )
            )

        case_responsibilities.sort(
            key=lambda item: (
                item.planned_end_at is None,
                item.planned_end_at or captured_at,
                str(item.id),
            )
        )
        finding_responsibilities.sort(key=lambda item: str(item.id))
        action_responsibilities.sort(
            key=lambda item: (
                item.due_at is None,
                item.due_at or captured_at,
                str(item.id),
            )
        )
        verification_queue.sort(key=lambda item: (item.raised_at, str(item.id)))

        due_soon_cases: list[WorkbenchCaseDeadline] = []
        overdue_cases: list[WorkbenchCaseDeadline] = []
        for case_item in case_responsibilities:
            if (
                case_item.planned_end_at is None
                or case_item.lifecycle not in _CASE_DEADLINE_LIFECYCLES
            ):
                continue
            case_deadline = WorkbenchCaseDeadline(
                id=case_item.id,
                title=case_item.title,
                lifecycle=case_item.lifecycle,
                deadline=case_item.planned_end_at,
            )
            if case_item.planned_end_at < captured_at:
                overdue_cases.append(case_deadline)
            elif case_item.planned_end_at <= captured_at + _DUE_SOON_WINDOW:
                due_soon_cases.append(case_deadline)

        due_soon_actions: list[WorkbenchActionDeadline] = []
        overdue_actions: list[WorkbenchActionDeadline] = []
        for action_item in action_responsibilities:
            if (
                action_item.due_at is None
                or action_item.lifecycle not in _ACTION_DEADLINE_LIFECYCLES
            ):
                continue
            action_deadline = WorkbenchActionDeadline(
                id=action_item.id,
                finding_id=action_item.finding_id,
                case_id=action_item.case_id,
                title=action_item.title,
                lifecycle=action_item.lifecycle,
                deadline=action_item.due_at,
            )
            if action_item.due_at < captured_at:
                overdue_actions.append(action_deadline)
            elif action_item.due_at <= captured_at + _DUE_SOON_WINDOW:
                due_soon_actions.append(action_deadline)

        due_soon_cases.sort(key=lambda item: (item.deadline, str(item.id)))
        due_soon_actions.sort(key=lambda item: (item.deadline, str(item.id)))
        overdue_cases.sort(key=lambda item: (item.deadline, str(item.id)))
        overdue_actions.sort(key=lambda item: (item.deadline, str(item.id)))

        return WorkbenchResponse(
            as_of=captured_at,
            case_responsibilities=tuple(case_responsibilities),
            finding_responsibilities=tuple(finding_responsibilities),
            action_responsibilities=tuple(action_responsibilities),
            verification_queue=tuple(verification_queue),
            due_soon=WorkbenchDeadlineBucket(
                cases=tuple(due_soon_cases),
                actions=tuple(due_soon_actions),
            ),
            overdue=WorkbenchDeadlineBucket(
                cases=tuple(overdue_cases),
                actions=tuple(overdue_actions),
            ),
        )

    def _load_case_members(self, actor: User) -> tuple[CaseMemberRecord, ...]:
        records = self._session.scalars(
            select(CaseMemberRecord).where(
                CaseMemberRecord.organization_id == actor.organization_id,
                CaseMemberRecord.user_id == actor.id,
            )
        )
        return tuple(records)

    def _load_finding_participants(self, actor: User) -> tuple[FindingParticipantRecord, ...]:
        actor_filter = FindingParticipantRecord.user_id == actor.id
        if actor.primary_department_id is not None:
            actor_filter = or_(
                actor_filter,
                FindingParticipantRecord.department_id == actor.primary_department_id,
            )
        records = self._session.scalars(
            select(FindingParticipantRecord).where(
                FindingParticipantRecord.organization_id == actor.organization_id,
                actor_filter,
            )
        )
        return tuple(records)

    def _load_action_assignees(self, actor: User) -> tuple[ActionAssigneeRecord, ...]:
        actor_filter = ActionAssigneeRecord.user_id == actor.id
        if actor.primary_department_id is not None:
            actor_filter = or_(
                actor_filter,
                ActionAssigneeRecord.department_id == actor.primary_department_id,
            )
        records = self._session.scalars(
            select(ActionAssigneeRecord).where(
                ActionAssigneeRecord.organization_id == actor.organization_id,
                actor_filter,
            )
        )
        return tuple(records)

    def _load_actions(
        self,
        actor: User,
        action_ids: set[UUID],
    ) -> tuple[ActionItemRecord, ...]:
        if not action_ids:
            return ()
        records = self._session.scalars(
            select(ActionItemRecord).where(
                ActionItemRecord.organization_id == actor.organization_id,
                ActionItemRecord.id.in_(action_ids),
            )
        )
        return tuple(records)

    def _load_findings(
        self,
        actor: User,
        finding_ids: set[UUID],
    ) -> tuple[FindingRecord, ...]:
        candidate_filter = FindingRecord.lifecycle == FindingLifecycle.VERIFYING.value
        if finding_ids:
            candidate_filter = or_(candidate_filter, FindingRecord.id.in_(finding_ids))
        records = self._session.scalars(
            select(FindingRecord).where(
                FindingRecord.organization_id == actor.organization_id,
                candidate_filter,
            )
        )
        return tuple(records)

    def _load_cases(
        self,
        actor: User,
        case_ids: set[UUID],
    ) -> tuple[ReviewCaseRecord, ...]:
        if not case_ids:
            return ()
        records = self._session.scalars(
            select(ReviewCaseRecord).where(
                ReviewCaseRecord.organization_id == actor.organization_id,
                ReviewCaseRecord.id.in_(case_ids),
            )
        )
        return tuple(records)

    def _load_scenario_versions(
        self,
        actor: User,
        cases: tuple[ReviewCaseRecord, ...],
    ) -> tuple[ScenarioVersionRecord, ...]:
        version_ids = {review_case.scenario_version_id for review_case in cases}
        if not version_ids:
            return ()
        return tuple(
            self._session.scalars(
                select(ScenarioVersionRecord).where(
                    ScenarioVersionRecord.organization_id == actor.organization_id,
                    ScenarioVersionRecord.id.in_(version_ids),
                )
            )
        )

    def _load_scenarios(
        self,
        actor: User,
        versions: tuple[ScenarioVersionRecord, ...],
    ) -> tuple[ScenarioRecord, ...]:
        scenario_ids = {version.scenario_id for version in versions}
        if not scenario_ids:
            return ()
        return tuple(
            self._session.scalars(
                select(ScenarioRecord).where(
                    ScenarioRecord.organization_id == actor.organization_id,
                    ScenarioRecord.id.in_(scenario_ids),
                )
            )
        )

    @staticmethod
    def _participant_fact(
        record: FindingParticipantRecord,
    ) -> tuple[RoleGrant, RelationshipKey]:
        if record.user_id is not None:
            actor_kind = ActorKind.USER
            source = PermissionSource.DIRECT
        else:
            actor_kind = ActorKind.DEPARTMENT
            source = PermissionSource.DEPARTMENT_MEMBERSHIP
        return (
            RoleGrant(role_key=record.role_key, actor_kind=actor_kind, source=source),
            (record.role_key, actor_kind, source),
        )

    @staticmethod
    def _assignee_fact(
        record: ActionAssigneeRecord,
    ) -> tuple[RoleGrant, RelationshipKey]:
        if record.user_id is not None:
            actor_kind = ActorKind.USER
            source = PermissionSource.DIRECT
        else:
            actor_kind = ActorKind.DEPARTMENT
            source = PermissionSource.DEPARTMENT_MEMBERSHIP
        return (
            RoleGrant(role_key=record.role, actor_kind=actor_kind, source=source),
            (record.role, actor_kind, source),
        )

    @staticmethod
    def _relationship_models(
        relationships: set[RelationshipKey],
    ) -> tuple[WorkbenchRelationship, ...]:
        return tuple(
            WorkbenchRelationship(
                role_key=role_key,
                actor_kind=actor_kind,
                source=source,
            )
            for role_key, actor_kind, source in sorted(
                relationships,
                key=lambda item: (item[0], item[1].value, item[2].value),
            )
        )
