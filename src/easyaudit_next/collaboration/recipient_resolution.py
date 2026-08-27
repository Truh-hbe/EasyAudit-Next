from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.persistence.models import UserRecord
from easyaudit_next.review_core.domain.models import ScenarioKey, ScenarioVersion
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActorKind,
    AuthorizationContext,
    CollaborationRecipientIntent,
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


@dataclass(slots=True)
class RecipientSnapshot:
    """Target-grouped current responsibility facts for one ReviewCase."""

    policy: ScenarioPolicy
    active_user_ids: tuple[UserId, ...]
    direct_case_member_ids: frozenset[UUID]
    case_grants: dict[UUID, set[RoleGrant]]
    finding_grants: dict[UUID, dict[UUID, set[RoleGrant]]]
    action_grants: dict[UUID, dict[UUID, set[RoleGrant]]]
    finding_by_id: dict[UUID, FindingRecord]
    actions_by_finding: dict[UUID, set[UUID]]
    case_finding_ids: frozenset[UUID]
    case_action_ids: frozenset[UUID]

    def case_context(self, user_id: UUID) -> AuthorizationContext:
        finding_grants: set[RoleGrant] = set()
        for finding_id in self.case_finding_ids:
            finding_grants.update(self.finding_grants.get(finding_id, {}).get(user_id, set()))
        action_grants: set[RoleGrant] = set()
        for action_id in self.case_action_ids:
            action_grants.update(self.action_grants.get(action_id, {}).get(user_id, set()))
        return AuthorizationContext(
            is_active_organization_user=True,
            case_role_grants=frozenset(self.case_grants.get(user_id, set())),
            finding_role_grants=frozenset(finding_grants),
            action_role_grants=frozenset(action_grants),
        )

    def finding_context(self, user_id: UUID, finding_id: UUID) -> AuthorizationContext:
        if finding_id not in self.finding_by_id:
            return AuthorizationContext(is_active_organization_user=True)
        action_grants: set[RoleGrant] = set()
        for action_id in self.actions_by_finding.get(finding_id, set()):
            action_grants.update(self.action_grants.get(action_id, {}).get(user_id, set()))
        return AuthorizationContext(
            is_active_organization_user=True,
            case_role_grants=frozenset(self.case_grants.get(user_id, set())),
            finding_role_grants=frozenset(
                self.finding_grants.get(finding_id, {}).get(user_id, set())
            ),
            action_role_grants=frozenset(action_grants),
        )

    def action_context(
        self,
        user_id: UUID,
        finding_id: UUID,
        action_item_id: UUID | None,
    ) -> AuthorizationContext:
        if action_item_id is None or action_item_id not in self.case_action_ids:
            return AuthorizationContext(is_active_organization_user=True)
        return AuthorizationContext(
            is_active_organization_user=True,
            case_role_grants=frozenset(self.case_grants.get(user_id, set())),
            finding_role_grants=frozenset(
                self.finding_grants.get(finding_id, {}).get(user_id, set())
            ),
            action_role_grants=frozenset(
                self.action_grants.get(action_item_id, {}).get(user_id, set())
            ),
        )


class RecipientResolver:
    """Resolve concrete Users through exact historical Scenario recipient semantics."""

    def __init__(self, session: Session, registry: ScenarioRegistry) -> None:
        self._session = session
        self._registry = registry

    def load(self, organization_id: OrganizationId, case_id: UUID) -> RecipientSnapshot:
        review_case = self._session.scalar(
            select(ReviewCaseRecord).where(
                ReviewCaseRecord.organization_id == organization_id,
                ReviewCaseRecord.id == case_id,
            )
        )
        if review_case is None:
            raise LookupError("ReviewCase not found")
        policy = self._policy(organization_id, review_case)

        users = tuple(
            self._session.scalars(
                select(UserRecord).where(
                    UserRecord.organization_id == organization_id,
                    UserRecord.is_active.is_(True),
                )
            )
        )
        user_ids = {record.id for record in users}
        users_by_department: dict[UUID, set[UUID]] = defaultdict(set)
        for user in users:
            if user.primary_department_id is not None:
                users_by_department[user.primary_department_id].add(user.id)

        case_members = tuple(
            self._session.scalars(
                select(CaseMemberRecord).where(
                    CaseMemberRecord.organization_id == organization_id,
                    CaseMemberRecord.case_id == case_id,
                )
            )
        )
        findings = tuple(
            self._session.scalars(
                select(FindingRecord).where(
                    FindingRecord.organization_id == organization_id,
                    FindingRecord.case_id == case_id,
                )
            )
        )
        finding_ids = {record.id for record in findings}
        participants: tuple[FindingParticipantRecord, ...] = ()
        actions: tuple[ActionItemRecord, ...] = ()
        if finding_ids:
            participants = tuple(
                self._session.scalars(
                    select(FindingParticipantRecord).where(
                        FindingParticipantRecord.organization_id == organization_id,
                        FindingParticipantRecord.finding_id.in_(finding_ids),
                    )
                )
            )
            actions = tuple(
                self._session.scalars(
                    select(ActionItemRecord).where(
                        ActionItemRecord.organization_id == organization_id,
                        ActionItemRecord.finding_id.in_(finding_ids),
                    )
                )
            )
        action_ids = {record.id for record in actions}
        assignees: tuple[ActionAssigneeRecord, ...] = ()
        if action_ids:
            assignees = tuple(
                self._session.scalars(
                    select(ActionAssigneeRecord).where(
                        ActionAssigneeRecord.organization_id == organization_id,
                        ActionAssigneeRecord.action_item_id.in_(action_ids),
                    )
                )
            )

        case_grants: dict[UUID, set[RoleGrant]] = defaultdict(set)
        for member in case_members:
            if member.user_id in user_ids:
                case_grants[member.user_id].add(
                    RoleGrant(
                        role_key=member.role_key,
                        actor_kind=ActorKind.USER,
                        source=PermissionSource.DIRECT,
                    )
                )

        finding_grants: dict[UUID, dict[UUID, set[RoleGrant]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for participant in participants:
            if participant.user_id is not None:
                grant = RoleGrant(
                    role_key=participant.role_key,
                    actor_kind=ActorKind.USER,
                    source=PermissionSource.DIRECT,
                )
                recipient_ids = (
                    {participant.user_id} if participant.user_id in user_ids else set()
                )
            elif participant.department_id is not None:
                grant = RoleGrant(
                    role_key=participant.role_key,
                    actor_kind=ActorKind.DEPARTMENT,
                    source=PermissionSource.DEPARTMENT_MEMBERSHIP,
                )
                recipient_ids = users_by_department.get(participant.department_id, set())
            else:
                continue
            for user_id in recipient_ids:
                finding_grants[participant.finding_id][user_id].add(grant)

        action_grants: dict[UUID, dict[UUID, set[RoleGrant]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for assignee in assignees:
            if assignee.user_id is not None:
                grant = RoleGrant(
                    role_key=assignee.role,
                    actor_kind=ActorKind.USER,
                    source=PermissionSource.DIRECT,
                )
                recipient_ids = {assignee.user_id} if assignee.user_id in user_ids else set()
            elif assignee.department_id is not None:
                grant = RoleGrant(
                    role_key=assignee.role,
                    actor_kind=ActorKind.DEPARTMENT,
                    source=PermissionSource.DEPARTMENT_MEMBERSHIP,
                )
                recipient_ids = users_by_department.get(assignee.department_id, set())
            else:
                continue
            for user_id in recipient_ids:
                action_grants[assignee.action_item_id][user_id].add(grant)

        finding_by_id = {record.id: record for record in findings}
        actions_by_finding: dict[UUID, set[UUID]] = defaultdict(set)
        for action in actions:
            actions_by_finding[action.finding_id].add(action.id)

        return RecipientSnapshot(
            policy=policy,
            active_user_ids=tuple(sorted((UserId(value) for value in user_ids), key=str)),
            direct_case_member_ids=frozenset(member.user_id for member in case_members),
            case_grants=case_grants,
            finding_grants=finding_grants,
            action_grants=action_grants,
            finding_by_id=finding_by_id,
            actions_by_finding=actions_by_finding,
            case_finding_ids=frozenset(finding_ids),
            case_action_ids=frozenset(action_ids),
        )

    @staticmethod
    def recipients(
        snapshot: RecipientSnapshot,
        intent: CollaborationRecipientIntent,
        *,
        finding_id: UUID | None = None,
        action_item_id: UUID | None = None,
        exclude_user_id: UserId | None = None,
    ) -> tuple[UserId, ...]:
        if action_item_id is not None and finding_id is None:
            raise ValueError("Action recipient resolution requires its Finding")

        recipients: set[UserId] = set()
        for user_id in snapshot.active_user_ids:
            if exclude_user_id is not None and user_id == exclude_user_id:
                continue
            if action_item_id is not None:
                context = snapshot.action_context(user_id, finding_id, action_item_id)
            elif finding_id is not None:
                context = snapshot.finding_context(user_id, finding_id)
            else:
                context = snapshot.case_context(user_id)
            if snapshot.policy.collaboration_recipients.is_recipient(intent, context):
                recipients.add(user_id)
        return tuple(sorted(recipients, key=str))

    def _policy(
        self,
        organization_id: OrganizationId,
        review_case: ReviewCaseRecord,
    ) -> ScenarioPolicy:
        version = self._session.scalar(
            select(ScenarioVersionRecord).where(
                ScenarioVersionRecord.organization_id == organization_id,
                ScenarioVersionRecord.id == review_case.scenario_version_id,
            )
        )
        if version is None:
            raise LookupError("ScenarioVersion not found for collaboration target")
        scenario = self._session.scalar(
            select(ScenarioRecord).where(
                ScenarioRecord.organization_id == organization_id,
                ScenarioRecord.id == version.scenario_id,
            )
        )
        if scenario is None:
            raise LookupError("Scenario not found for collaboration target")
        return self._registry.get(
            ScenarioKey(scenario.key),
            ScenarioVersion(version.version),
        )
