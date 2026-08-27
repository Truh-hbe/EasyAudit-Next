from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from easyaudit_next.notifications.models import (
    ActionItemNotificationSubject,
    FindingNotificationSubject,
    NotificationKind,
)
from easyaudit_next.notifications.service import NotificationService
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.domain.models import User
from easyaudit_next.platform.persistence.models import UserRecord
from easyaudit_next.review_core.domain.ids import ActionItemId, ActivityId, FindingId
from easyaudit_next.review_core.domain.models import (
    ActionItemActivitySubject,
    Activity,
    FindingActivitySubject,
    ScenarioKey,
    ScenarioVersion,
)
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
from easyaudit_next.review_core.persistence.repositories import SqlAlchemyReviewCoreRepository

MANAGE_CASE_MEMBERS_PERMISSION = "manage_case_members"
VIEW_CASE_PERMISSION = "view_case"
VIEW_FINDING_PERMISSION = "view_finding"


class NudgeValidationError(ValueError):
    """Raised when a visible, authorized nudge has no eligible recipient."""


@dataclass(frozen=True, slots=True)
class NudgeResult:
    activity_id: ActivityId
    recipient_count: int


class ManualNudgeService:
    """Human nudge orchestration over existing Review facts and Scenario responsibility."""

    def __init__(
        self,
        session: Session,
        registry: ScenarioRegistry,
        notifications: NotificationService,
    ) -> None:
        self._session = session
        self._registry = registry
        self._notifications = notifications
        self._review_repository = SqlAlchemyReviewCoreRepository(session)

    def nudge_finding(
        self,
        actor: User,
        finding_id: UUID,
        *,
        occurred_at: datetime | None = None,
    ) -> NudgeResult:
        finding = self._session.scalar(
            select(FindingRecord).where(
                FindingRecord.organization_id == actor.organization_id,
                FindingRecord.id == finding_id,
            )
        )
        if finding is None:
            raise LookupError("Finding not found")
        snapshot = self._snapshot(actor, finding.case_id)
        self._authorize_sender(actor, snapshot, finding.id)
        recipients = self._recipients(
            actor,
            snapshot,
            CollaborationRecipientIntent.FINDING_RECTIFICATION,
            finding_id=finding.id,
        )
        if not recipients:
            raise NudgeValidationError("No eligible nudge recipients")

        now = self._occurred_at(occurred_at)
        activity = Activity(
            id=ActivityId(uuid4()),
            organization_id=actor.organization_id,
            subject=FindingActivitySubject(FindingId(finding.id)),
            event_type="finding.nudged",
            actor_id=actor.id,
            occurred_at=now,
            metadata={"recipient_count": len(recipients)},
        )
        self._review_repository.add_activity(activity)
        self._notifications.deliver(
            organization_id=actor.organization_id,
            recipients=recipients,
            kind=NotificationKind.MANUAL_FINDING_NUDGE,
            origin_activity_id=activity.id,
            subject=FindingNotificationSubject(FindingId(finding.id)),
            title="Finding nudge",
            body="A Finding needs your attention.",
            created_at=now,
        )
        return NudgeResult(activity_id=activity.id, recipient_count=len(recipients))

    def nudge_action_item(
        self,
        actor: User,
        action_item_id: UUID,
        *,
        occurred_at: datetime | None = None,
    ) -> NudgeResult:
        action = self._session.scalar(
            select(ActionItemRecord).where(
                ActionItemRecord.organization_id == actor.organization_id,
                ActionItemRecord.id == action_item_id,
            )
        )
        if action is None:
            raise LookupError("ActionItem not found")
        finding = self._session.scalar(
            select(FindingRecord).where(
                FindingRecord.organization_id == actor.organization_id,
                FindingRecord.id == action.finding_id,
            )
        )
        if finding is None:
            raise LookupError("ActionItem not found")

        snapshot = self._snapshot(actor, finding.case_id)
        self._authorize_sender(actor, snapshot, finding.id)
        recipients = self._recipients(
            actor,
            snapshot,
            CollaborationRecipientIntent.ACTION_EXECUTION,
            finding_id=finding.id,
            action_item_id=action.id,
        )
        if not recipients:
            raise NudgeValidationError("No eligible nudge recipients")

        now = self._occurred_at(occurred_at)
        typed_action_id = ActionItemId(action.id)
        activity = Activity(
            id=ActivityId(uuid4()),
            organization_id=actor.organization_id,
            subject=ActionItemActivitySubject(typed_action_id),
            event_type="action_item.nudged",
            actor_id=actor.id,
            occurred_at=now,
            metadata={"recipient_count": len(recipients)},
        )
        self._review_repository.add_activity(activity)
        self._notifications.deliver(
            organization_id=actor.organization_id,
            recipients=recipients,
            kind=NotificationKind.MANUAL_ACTION_NUDGE,
            origin_activity_id=activity.id,
            subject=ActionItemNotificationSubject(typed_action_id),
            title="ActionItem nudge",
            body="An ActionItem needs your attention.",
            created_at=now,
        )
        return NudgeResult(activity_id=activity.id, recipient_count=len(recipients))

    def _snapshot(self, actor: User, case_id: UUID) -> "_NudgeSnapshot":
        if not actor.is_active:
            raise LookupError("ReviewCase not found")
        review_case = self._session.scalar(
            select(ReviewCaseRecord).where(
                ReviewCaseRecord.organization_id == actor.organization_id,
                ReviewCaseRecord.id == case_id,
            )
        )
        if review_case is None:
            raise LookupError("ReviewCase not found")
        policy = self._policy(actor.organization_id, review_case)

        users = tuple(
            self._session.scalars(
                select(UserRecord).where(
                    UserRecord.organization_id == actor.organization_id,
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
                    CaseMemberRecord.organization_id == actor.organization_id,
                    CaseMemberRecord.case_id == case_id,
                )
            )
        )
        findings = tuple(
            self._session.scalars(
                select(FindingRecord).where(
                    FindingRecord.organization_id == actor.organization_id,
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
                        FindingParticipantRecord.organization_id == actor.organization_id,
                        FindingParticipantRecord.finding_id.in_(finding_ids),
                    )
                )
            )
            actions = tuple(
                self._session.scalars(
                    select(ActionItemRecord).where(
                        ActionItemRecord.organization_id == actor.organization_id,
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
                        ActionAssigneeRecord.organization_id == actor.organization_id,
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
            participant_grant: RoleGrant
            participant_recipient_ids: set[UUID]
            if participant.user_id is not None:
                participant_grant = RoleGrant(
                    role_key=participant.role_key,
                    actor_kind=ActorKind.USER,
                    source=PermissionSource.DIRECT,
                )
                participant_recipient_ids = (
                    {participant.user_id} if participant.user_id in user_ids else set()
                )
            elif participant.department_id is not None:
                participant_grant = RoleGrant(
                    role_key=participant.role_key,
                    actor_kind=ActorKind.DEPARTMENT,
                    source=PermissionSource.DEPARTMENT_MEMBERSHIP,
                )
                participant_recipient_ids = users_by_department.get(
                    participant.department_id,
                    set(),
                )
            else:
                continue
            for user_id in participant_recipient_ids:
                finding_grants[participant.finding_id][user_id].add(participant_grant)

        action_grants: dict[UUID, dict[UUID, set[RoleGrant]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for assignee in assignees:
            assignee_grant: RoleGrant
            assignee_recipient_ids: set[UUID]
            if assignee.user_id is not None:
                assignee_grant = RoleGrant(
                    role_key=assignee.role,
                    actor_kind=ActorKind.USER,
                    source=PermissionSource.DIRECT,
                )
                assignee_recipient_ids = (
                    {assignee.user_id} if assignee.user_id in user_ids else set()
                )
            elif assignee.department_id is not None:
                assignee_grant = RoleGrant(
                    role_key=assignee.role,
                    actor_kind=ActorKind.DEPARTMENT,
                    source=PermissionSource.DEPARTMENT_MEMBERSHIP,
                )
                assignee_recipient_ids = users_by_department.get(
                    assignee.department_id,
                    set(),
                )
            else:
                continue
            for user_id in assignee_recipient_ids:
                action_grants[assignee.action_item_id][user_id].add(assignee_grant)

        finding_by_id = {record.id: record for record in findings}
        actions_by_finding: dict[UUID, set[UUID]] = defaultdict(set)
        for action in actions:
            actions_by_finding[action.finding_id].add(action.id)

        return _NudgeSnapshot(
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

    def _authorize_sender(
        self,
        actor: User,
        snapshot: "_NudgeSnapshot",
        finding_id: UUID,
    ) -> None:
        if actor.id not in snapshot.direct_case_member_ids:
            raise LookupError("ReviewCase not found")
        case_context = snapshot.case_context(actor.id)
        if not snapshot.policy.authorization.allows(
            MANAGE_CASE_MEMBERS_PERMISSION,
            case_context,
        ):
            raise LookupError("ReviewCase not found")
        if not snapshot.policy.authorization.allows(VIEW_CASE_PERMISSION, case_context):
            raise LookupError("ReviewCase not found")
        finding_context = snapshot.finding_context(actor.id, finding_id)
        if not snapshot.policy.authorization.allows(VIEW_FINDING_PERMISSION, finding_context):
            raise LookupError("Finding not found")

    def _recipients(
        self,
        actor: User,
        snapshot: "_NudgeSnapshot",
        intent: CollaborationRecipientIntent,
        *,
        finding_id: UUID,
        action_item_id: UUID | None = None,
    ) -> tuple[UserId, ...]:
        recipients: set[UserId] = set()
        for user_id in snapshot.active_user_ids:
            if user_id == actor.id:
                continue
            context = (
                snapshot.action_context(user_id, finding_id, action_item_id)
                if action_item_id is not None
                else snapshot.finding_context(user_id, finding_id)
            )
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
            raise LookupError("ScenarioVersion not found for nudge target")
        scenario = self._session.scalar(
            select(ScenarioRecord).where(
                ScenarioRecord.organization_id == organization_id,
                ScenarioRecord.id == version.scenario_id,
            )
        )
        if scenario is None:
            raise LookupError("Scenario not found for nudge target")
        return self._registry.get(
            ScenarioKey(scenario.key),
            ScenarioVersion(version.version),
        )

    @staticmethod
    def _occurred_at(value: datetime | None) -> datetime:
        occurred_at = value or datetime.now(UTC)
        if occurred_at.utcoffset() is None:
            raise ValueError("Nudge occurred_at must include UTC offset")
        return occurred_at


@dataclass(slots=True)
class _NudgeSnapshot:
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
