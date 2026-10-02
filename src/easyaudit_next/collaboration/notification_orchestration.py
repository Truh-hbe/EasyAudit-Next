from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from easyaudit_next.notifications.copy import COPY
from easyaudit_next.notifications.models import (
    ActionItemNotificationSubject,
    FindingNotificationSubject,
    NotificationKind,
    ReviewCaseNotificationSubject,
)
from easyaudit_next.notifications.service import NotificationService
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.persistence.models import UserRecord
from easyaudit_next.review_core.application.mutation_results import (
    ActionAssigneeAddedResult,
    CaseMemberAddedResult,
    FindingParticipantAddedResult,
    RectificationSubmissionResult,
)
from easyaudit_next.review_core.domain.models import (
    FindingLifecycle,
    ParticipantActor,
    ScenarioKey,
    ScenarioVersion,
    UserActor,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActorKind,
    AuthorizationContext,
    PermissionSource,
    RoleGrant,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
from easyaudit_next.review_core.persistence.models import (
    ActionAssigneeRecord,
    ActionItemRecord,
    CaseMemberRecord,
    FindingParticipantRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)

VERIFY_FINDING_PERMISSION = "verify_finding"


class NotificationOrchestrator:
    """Translate exact Review Core mutation results into durable user deliveries."""

    def __init__(
        self,
        session: Session,
        registry: ScenarioRegistry,
        notifications: NotificationService,
    ) -> None:
        self._session = session
        self._registry = registry
        self._notifications = notifications

    def case_member_added(self, result: CaseMemberAddedResult) -> None:
        member = result.member
        recipients = self._active_direct_user(
            member.organization_id,
            member.user_id,
        )
        self._notifications.deliver(
            organization_id=member.organization_id,
            recipients=recipients,
            kind=NotificationKind.CASE_MEMBERSHIP_ADDED,
            origin_activity_id=result.activity_id,
            subject=ReviewCaseNotificationSubject(member.case_id),
            title=COPY[NotificationKind.CASE_MEMBERSHIP_ADDED].title,
            body=COPY[NotificationKind.CASE_MEMBERSHIP_ADDED].body,
        )

    def finding_participant_added(self, result: FindingParticipantAddedResult) -> None:
        participant = result.participant
        recipients = self._relationship_recipients(
            participant.organization_id,
            participant.actor,
        )
        self._notifications.deliver(
            organization_id=participant.organization_id,
            recipients=recipients,
            kind=NotificationKind.FINDING_PARTICIPANT_ADDED,
            origin_activity_id=result.activity_id,
            subject=FindingNotificationSubject(participant.finding_id),
            title=COPY[NotificationKind.FINDING_PARTICIPANT_ADDED].title,
            body=COPY[NotificationKind.FINDING_PARTICIPANT_ADDED].body,
        )

    def action_assignee_added(self, result: ActionAssigneeAddedResult) -> None:
        assignee = result.assignee
        recipients = self._relationship_recipients(
            assignee.organization_id,
            assignee.actor,
        )
        self._notifications.deliver(
            organization_id=assignee.organization_id,
            recipients=recipients,
            kind=NotificationKind.ACTION_ASSIGNEE_ADDED,
            origin_activity_id=result.activity_id,
            subject=ActionItemNotificationSubject(assignee.action_item_id),
            title=COPY[NotificationKind.ACTION_ASSIGNEE_ADDED].title,
            body=COPY[NotificationKind.ACTION_ASSIGNEE_ADDED].body,
        )

    def rectification_submitted(self, result: RectificationSubmissionResult) -> None:
        finding = result.finding
        if finding.lifecycle is not FindingLifecycle.VERIFYING:
            return
        recipients = self._verification_recipients(
            finding.organization_id,
            finding.id,
            finding.case_id,
        )
        self._notifications.deliver(
            organization_id=finding.organization_id,
            recipients=recipients,
            kind=NotificationKind.FINDING_SUBMITTED_FOR_VERIFICATION,
            origin_activity_id=result.activity_id,
            subject=FindingNotificationSubject(finding.id),
            title=COPY[NotificationKind.FINDING_SUBMITTED_FOR_VERIFICATION].title,
            body=COPY[NotificationKind.FINDING_SUBMITTED_FOR_VERIFICATION].body,
        )

    def _relationship_recipients(
        self,
        organization_id: OrganizationId,
        actor: ParticipantActor,
    ) -> tuple[UserId, ...]:
        if isinstance(actor, UserActor):
            return self._active_direct_user(organization_id, actor.user_id)
        return self._active_department_users(organization_id, actor.department_id)

    def _active_direct_user(
        self,
        organization_id: OrganizationId,
        user_id: UserId,
    ) -> tuple[UserId, ...]:
        persisted_id = self._session.scalar(
            select(UserRecord.id).where(
                UserRecord.organization_id == organization_id,
                UserRecord.id == user_id,
                UserRecord.is_active.is_(True),
            )
        )
        return () if persisted_id is None else (UserId(persisted_id),)

    def _active_department_users(
        self,
        organization_id: OrganizationId,
        department_id: DepartmentId,
    ) -> tuple[UserId, ...]:
        return tuple(
            UserId(user_id)
            for user_id in self._session.scalars(
                select(UserRecord.id)
                .where(
                    UserRecord.organization_id == organization_id,
                    UserRecord.primary_department_id == department_id,
                    UserRecord.is_active.is_(True),
                )
                .order_by(UserRecord.id)
            )
        )

    def _verification_recipients(
        self,
        organization_id: OrganizationId,
        finding_id: UUID,
        case_id: UUID,
    ) -> tuple[UserId, ...]:
        review_case = self._session.scalar(
            select(ReviewCaseRecord).where(
                ReviewCaseRecord.organization_id == organization_id,
                ReviewCaseRecord.id == case_id,
            )
        )
        if review_case is None:
            raise LookupError("ReviewCase not found for verification notification")
        scenario_version = self._session.scalar(
            select(ScenarioVersionRecord).where(
                ScenarioVersionRecord.organization_id == organization_id,
                ScenarioVersionRecord.id == review_case.scenario_version_id,
            )
        )
        if scenario_version is None:
            raise LookupError("ScenarioVersion not found for verification notification")
        scenario = self._session.scalar(
            select(ScenarioRecord).where(
                ScenarioRecord.organization_id == organization_id,
                ScenarioRecord.id == scenario_version.scenario_id,
            )
        )
        if scenario is None:
            raise LookupError("Scenario not found for verification notification")
        policy = self._registry.get(
            ScenarioKey(scenario.key),
            ScenarioVersion(scenario_version.version),
        )

        active_users = tuple(
            self._session.scalars(
                select(UserRecord).where(
                    UserRecord.organization_id == organization_id,
                    UserRecord.is_active.is_(True),
                )
            )
        )
        users_by_department: dict[UUID, set[UUID]] = defaultdict(set)
        for user in active_users:
            if user.primary_department_id is not None:
                users_by_department[user.primary_department_id].add(user.id)

        case_grants: dict[UUID, set[RoleGrant]] = defaultdict(set)
        for member in self._session.scalars(
            select(CaseMemberRecord).where(
                CaseMemberRecord.organization_id == organization_id,
                CaseMemberRecord.case_id == case_id,
            )
        ):
            case_grants[member.user_id].add(
                RoleGrant(
                    role_key=member.role_key,
                    actor_kind=ActorKind.USER,
                    source=PermissionSource.DIRECT,
                )
            )

        finding_grants: dict[UUID, set[RoleGrant]] = defaultdict(set)
        for participant in self._session.scalars(
            select(FindingParticipantRecord).where(
                FindingParticipantRecord.organization_id == organization_id,
                FindingParticipantRecord.finding_id == finding_id,
            )
        ):
            if participant.user_id is not None:
                finding_grants[participant.user_id].add(
                    RoleGrant(
                        role_key=participant.role_key,
                        actor_kind=ActorKind.USER,
                        source=PermissionSource.DIRECT,
                    )
                )
            elif participant.department_id is not None:
                grant = RoleGrant(
                    role_key=participant.role_key,
                    actor_kind=ActorKind.DEPARTMENT,
                    source=PermissionSource.DEPARTMENT_MEMBERSHIP,
                )
                for user_id in users_by_department.get(
                    participant.department_id,
                    set(),
                ):
                    finding_grants[user_id].add(grant)

        actions = tuple(
            self._session.scalars(
                select(ActionItemRecord).where(
                    ActionItemRecord.organization_id == organization_id,
                    ActionItemRecord.finding_id == finding_id,
                )
            )
        )
        action_ids = {action.id for action in actions}
        action_grants: dict[UUID, set[RoleGrant]] = defaultdict(set)
        if action_ids:
            for assignee in self._session.scalars(
                select(ActionAssigneeRecord).where(
                    ActionAssigneeRecord.organization_id == organization_id,
                    ActionAssigneeRecord.action_item_id.in_(action_ids),
                )
            ):
                if assignee.user_id is not None:
                    action_grants[assignee.user_id].add(
                        RoleGrant(
                            role_key=assignee.role,
                            actor_kind=ActorKind.USER,
                            source=PermissionSource.DIRECT,
                        )
                    )
                elif assignee.department_id is not None:
                    grant = RoleGrant(
                        role_key=assignee.role,
                        actor_kind=ActorKind.DEPARTMENT,
                        source=PermissionSource.DEPARTMENT_MEMBERSHIP,
                    )
                    for user_id in users_by_department.get(
                        assignee.department_id,
                        set(),
                    ):
                        action_grants[user_id].add(grant)

        recipients: list[UserId] = []
        for user in active_users:
            context = AuthorizationContext(
                is_active_organization_user=True,
                case_role_grants=frozenset(case_grants.get(user.id, set())),
                finding_role_grants=frozenset(finding_grants.get(user.id, set())),
                action_role_grants=frozenset(action_grants.get(user.id, set())),
            )
            if policy.authorization.allows(VERIFY_FINDING_PERMISSION, context):
                recipients.append(UserId(user.id))
        return tuple(sorted(recipients, key=str))
