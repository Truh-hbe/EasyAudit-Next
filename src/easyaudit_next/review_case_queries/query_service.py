from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.domain.models import User
from easyaudit_next.review_core.domain.ids import ReviewCaseId, ReviewPlanId
from easyaudit_next.review_core.domain.models import (
    ReviewCase,
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

VIEW_CASE_PERMISSION = "view_case"

# Seven SELECT categories, independent of the number of Cases/Findings/Actions in the
# organization: CaseMember facts, FindingParticipant facts, ActionAssignee facts,
# parent Actions, parent Findings, Scenario versions, and candidate Cases.
SELECT_QUERY_BOUND = 7


@dataclass(frozen=True, slots=True)
class ReviewCaseCollection:
    """Bounded read envelope over authoritative ReviewCase resources."""

    items: tuple[ReviewCase, ...]
    total: int
    limit: int
    offset: int


class ReviewCaseCollectionQueryService:
    """Bulk-authorize ReviewCases before stable ordering and pagination."""

    def __init__(self, session: Session, registry: ScenarioRegistry) -> None:
        self._session = session
        self._registry = registry

    def list_review_cases(
        self,
        actor: User,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> ReviewCaseCollection:
        if not actor.is_active:
            raise PermissionError("Active organization user required")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if offset < 0:
            raise ValueError("offset must be non-negative")

        case_members = self._load_case_members(actor)
        finding_participants = self._load_finding_participants(actor)
        action_assignees = self._load_action_assignees(actor)
        actions = self._load_actions(
            actor,
            {assignee.action_item_id for assignee in action_assignees},
        )
        action_by_id = {action.id: action for action in actions}

        finding_ids = {participant.finding_id for participant in finding_participants}
        finding_ids.update(action.finding_id for action in actions)
        findings = self._load_findings(actor, finding_ids)
        finding_by_id = {finding.id: finding for finding in findings}

        scenario_facts = self._load_scenario_facts(actor)
        scenario_fact_by_version_id = {
            version.id: (version, scenario) for version, scenario in scenario_facts
        }

        case_grants: dict[UUID, set[RoleGrant]] = defaultdict(set)
        candidate_case_ids: set[UUID] = set()
        for member in case_members:
            candidate_case_ids.add(member.case_id)
            case_grants[member.case_id].add(
                RoleGrant(
                    role_key=member.role_key,
                    actor_kind=ActorKind.USER,
                    source=PermissionSource.DIRECT,
                )
            )

        finding_grants_by_case: dict[UUID, set[RoleGrant]] = defaultdict(set)
        for participant in finding_participants:
            finding = finding_by_id.get(participant.finding_id)
            if finding is None:
                continue
            candidate_case_ids.add(finding.case_id)
            finding_grants_by_case[finding.case_id].add(
                self._participant_grant(actor, participant)
            )

        action_grants_by_case: dict[UUID, set[RoleGrant]] = defaultdict(set)
        for assignee in action_assignees:
            action = action_by_id.get(assignee.action_item_id)
            if action is None:
                continue
            finding = finding_by_id.get(action.finding_id)
            if finding is None:
                continue
            candidate_case_ids.add(finding.case_id)
            action_grants_by_case[finding.case_id].add(
                self._assignee_grant(actor, assignee)
            )

        # Candidate discovery is only a performance boundary. A Scenario version whose
        # exact VIEW_CASE policy allows an active user with no relationship grants must
        # still contribute every Case of that version, so discovery never becomes a
        # second authorization rule.
        empty_context = AuthorizationContext(is_active_organization_user=actor.is_active)
        grant_free_version_ids: set[UUID] = set()
        for version, scenario in scenario_facts:
            policy = self._registry.get(
                ScenarioKey(scenario.key),
                ScenarioVersion(version.version),
            )
            if policy.authorization.allows(VIEW_CASE_PERMISSION, empty_context):
                grant_free_version_ids.add(version.id)

        candidates = self._load_candidate_cases(
            actor,
            candidate_case_ids,
            grant_free_version_ids,
        )

        authorized: list[ReviewCaseRecord] = []
        for record in candidates:
            policy = self._policy_for_case(record, scenario_fact_by_version_id)
            context = AuthorizationContext(
                is_active_organization_user=actor.is_active,
                case_role_grants=frozenset(case_grants.get(record.id, set())),
                finding_role_grants=frozenset(
                    finding_grants_by_case.get(record.id, set())
                ),
                action_role_grants=frozenset(
                    action_grants_by_case.get(record.id, set())
                ),
            )
            if policy.authorization.allows(VIEW_CASE_PERMISSION, context):
                authorized.append(record)

        authorized.sort(
            key=lambda record: (record.created_at, record.id.int),
            reverse=True,
        )
        total = len(authorized)
        page = authorized[offset : offset + limit]
        return ReviewCaseCollection(
            items=tuple(
                self._case_to_domain(record, scenario_fact_by_version_id)
                for record in page
            ),
            total=total,
            limit=limit,
            offset=offset,
        )

    def _load_case_members(self, actor: User) -> tuple[CaseMemberRecord, ...]:
        return tuple(
            self._session.scalars(
                select(CaseMemberRecord).where(
                    CaseMemberRecord.organization_id == actor.organization_id,
                    CaseMemberRecord.user_id == actor.id,
                )
            )
        )

    def _load_finding_participants(
        self,
        actor: User,
    ) -> tuple[FindingParticipantRecord, ...]:
        actor_predicates = [FindingParticipantRecord.user_id == actor.id]
        if actor.primary_department_id is not None:
            actor_predicates.append(
                FindingParticipantRecord.department_id == actor.primary_department_id
            )
        return tuple(
            self._session.scalars(
                select(FindingParticipantRecord).where(
                    FindingParticipantRecord.organization_id == actor.organization_id,
                    or_(*actor_predicates),
                )
            )
        )

    def _load_action_assignees(
        self,
        actor: User,
    ) -> tuple[ActionAssigneeRecord, ...]:
        actor_predicates = [ActionAssigneeRecord.user_id == actor.id]
        if actor.primary_department_id is not None:
            actor_predicates.append(
                ActionAssigneeRecord.department_id == actor.primary_department_id
            )
        return tuple(
            self._session.scalars(
                select(ActionAssigneeRecord).where(
                    ActionAssigneeRecord.organization_id == actor.organization_id,
                    or_(*actor_predicates),
                )
            )
        )

    def _load_actions(
        self,
        actor: User,
        action_ids: set[UUID],
    ) -> tuple[ActionItemRecord, ...]:
        return tuple(
            self._session.scalars(
                select(ActionItemRecord).where(
                    ActionItemRecord.organization_id == actor.organization_id,
                    ActionItemRecord.id.in_(action_ids),
                )
            )
        )

    def _load_findings(
        self,
        actor: User,
        finding_ids: set[UUID],
    ) -> tuple[FindingRecord, ...]:
        return tuple(
            self._session.scalars(
                select(FindingRecord).where(
                    FindingRecord.organization_id == actor.organization_id,
                    FindingRecord.id.in_(finding_ids),
                )
            )
        )

    def _load_scenario_facts(
        self,
        actor: User,
    ) -> tuple[tuple[ScenarioVersionRecord, ScenarioRecord], ...]:
        rows = self._session.execute(
            select(ScenarioVersionRecord, ScenarioRecord)
            .join(
                ScenarioRecord,
                and_(
                    ScenarioRecord.id == ScenarioVersionRecord.scenario_id,
                    ScenarioRecord.organization_id
                    == ScenarioVersionRecord.organization_id,
                ),
            )
            .where(
                ScenarioVersionRecord.organization_id == actor.organization_id,
                ScenarioRecord.organization_id == actor.organization_id,
            )
        ).all()
        return tuple((version, scenario) for version, scenario in rows)

    def _load_candidate_cases(
        self,
        actor: User,
        candidate_case_ids: set[UUID],
        grant_free_version_ids: set[UUID],
    ) -> tuple[ReviewCaseRecord, ...]:
        return tuple(
            self._session.scalars(
                select(ReviewCaseRecord).where(
                    ReviewCaseRecord.organization_id == actor.organization_id,
                    or_(
                        ReviewCaseRecord.id.in_(candidate_case_ids),
                        ReviewCaseRecord.scenario_version_id.in_(grant_free_version_ids),
                    ),
                )
            )
        )

    def _policy_for_case(
        self,
        record: ReviewCaseRecord,
        scenario_fact_by_version_id: dict[
            UUID,
            tuple[ScenarioVersionRecord, ScenarioRecord],
        ],
    ) -> ScenarioPolicy:
        fact = scenario_fact_by_version_id.get(record.scenario_version_id)
        if fact is None:
            raise LookupError("Scenario version not found for Product ReviewCase")
        version, scenario = fact
        return self._registry.get(
            ScenarioKey(scenario.key),
            ScenarioVersion(version.version),
        )

    @staticmethod
    def _participant_grant(
        actor: User,
        participant: FindingParticipantRecord,
    ) -> RoleGrant:
        if participant.user_id == actor.id:
            return RoleGrant(
                role_key=participant.role_key,
                actor_kind=ActorKind.USER,
                source=PermissionSource.DIRECT,
            )
        if (
            actor.primary_department_id is not None
            and participant.department_id == actor.primary_department_id
        ):
            return RoleGrant(
                role_key=participant.role_key,
                actor_kind=ActorKind.DEPARTMENT,
                source=PermissionSource.DEPARTMENT_MEMBERSHIP,
            )
        raise RuntimeError("FindingParticipant escaped actor-scoped candidate query")

    @staticmethod
    def _assignee_grant(
        actor: User,
        assignee: ActionAssigneeRecord,
    ) -> RoleGrant:
        if assignee.user_id == actor.id:
            return RoleGrant(
                role_key=assignee.role,
                actor_kind=ActorKind.USER,
                source=PermissionSource.DIRECT,
            )
        if (
            actor.primary_department_id is not None
            and assignee.department_id == actor.primary_department_id
        ):
            return RoleGrant(
                role_key=assignee.role,
                actor_kind=ActorKind.DEPARTMENT,
                source=PermissionSource.DEPARTMENT_MEMBERSHIP,
            )
        raise RuntimeError("ActionAssignee escaped actor-scoped candidate query")

    @staticmethod
    def _case_to_domain(
        record: ReviewCaseRecord,
        scenario_fact_by_version_id: dict[
            UUID,
            tuple[ScenarioVersionRecord, ScenarioRecord],
        ],
    ) -> ReviewCase:
        fact = scenario_fact_by_version_id.get(record.scenario_version_id)
        if fact is None:
            raise LookupError("Scenario version not found for Product ReviewCase")
        version, scenario = fact
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
            scenario_data=dict(record.scenario_data_json),
        )
