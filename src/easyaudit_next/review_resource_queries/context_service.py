from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from easyaudit_next.platform.domain.models import User
from easyaudit_next.platform.persistence.models import DepartmentRecord, UserRecord
from easyaudit_next.review_core.application.authorization import (
    build_rectification_authorization_context,
)
from easyaudit_next.review_core.application.review_findings import (
    MANAGE_FINDING_PARTICIPANTS_PERMISSION,
    FindingLifecycleService,
)
from easyaudit_next.review_core.application.review_planning import ReviewAuthorizationError
from easyaudit_next.review_core.application.review_rectification import (
    MANAGE_ACTION_ASSIGNEES_PERMISSION,
    TRANSFER_AND_REOPEN_ACTION_PERMISSION,
    RectificationService,
)
from easyaudit_next.review_core.domain.ids import ActionItemId, FindingId
from easyaudit_next.review_core.domain.models import (
    ActionAssignee,
    ActionItem,
    AssignmentRole,
    DepartmentActor,
    Finding,
    FindingParticipant,
    ReviewCase,
    Submission,
    UserActor,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActionItemOperationContext,
    ActorKind,
    AuthorizationContext,
    FindingOperationContext,
    PermissionSource,
    RoleGrant,
    RoleSpecification,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioPolicy, ScenarioRegistry
from easyaudit_next.review_core.persistence.models import ActivityRecord
from easyaudit_next.review_core.persistence.verification_repositories import (
    SqlAlchemyVerificationClosureRepository,
)


@dataclass(frozen=True, slots=True)
class FindingParticipantView:
    finding_id: UUID
    actor_kind: ActorKind
    actor_id: UUID
    role_key: str
    assigned_at: datetime
    display_name: str


@dataclass(frozen=True, slots=True)
class ActionAssigneeView:
    action_item_id: UUID
    actor_kind: ActorKind
    actor_id: UUID
    role: AssignmentRole
    assigned_at: datetime
    display_name: str


@dataclass(frozen=True, slots=True)
class AssignmentCandidateView:
    actor_kind: ActorKind
    actor_id: UUID
    display_name: str


@dataclass(frozen=True, slots=True)
class ResourceActivityView:
    id: UUID
    subject_id: UUID
    event_type: str
    actor_id: UUID | None
    occurred_at: datetime


class ReviewResourceContextQueryService:
    """M3.5.3 presentation reads gated by current target authorization."""

    def __init__(
        self,
        session: Session,
        finding_service: FindingLifecycleService,
        rectification_service: RectificationService,
        registry: ScenarioRegistry,
    ) -> None:
        self._session = session
        self._finding_service = finding_service
        self._rectification_service = rectification_service
        self._registry = registry
        self._repository = SqlAlchemyVerificationClosureRepository(session)

    def list_finding_participant_views(
        self,
        actor: User,
        finding_id: FindingId,
    ) -> tuple[FindingParticipantView, ...]:
        participants = self._finding_service.list_participants(actor, finding_id)
        names = self._relationship_names(actor, participants)
        return tuple(
            FindingParticipantView(
                finding_id=participant.finding_id,
                actor_kind=identity[0],
                actor_id=identity[1],
                role_key=participant.role_key,
                assigned_at=participant.assigned_at,
                display_name=names[identity],
            )
            for participant in participants
            for identity in (self._participant_identity(participant),)
        )

    def list_action_assignee_views(
        self,
        actor: User,
        action_item_id: ActionItemId,
    ) -> tuple[ActionAssigneeView, ...]:
        assignees = self._rectification_service.list_assignees(actor, action_item_id)
        names = self._relationship_names(actor, assignees)
        return tuple(
            ActionAssigneeView(
                action_item_id=assignee.action_item_id,
                actor_kind=identity[0],
                actor_id=identity[1],
                role=assignee.role,
                assigned_at=assignee.assigned_at,
                display_name=names[identity],
            )
            for assignee in assignees
            for identity in (self._assignee_identity(assignee),)
        )

    def search_finding_participant_candidates(
        self,
        actor: User,
        finding_id: FindingId,
        *,
        role_key: str,
        actor_kind: ActorKind,
        search_text: str,
        limit: int,
    ) -> tuple[AssignmentCandidateView, ...]:
        finding, review_case, policy, context = self._finding_policy_context(actor, finding_id)
        if not policy.authorization.allows(MANAGE_FINDING_PARTICIPANTS_PERMISSION, context):
            raise ReviewAuthorizationError(
                "lead or auditor role required to manage FindingParticipant"
            )
        participant_roles = frozenset(
            item.role_key
            for item in self._repository.list_finding_participants(
                actor.organization_id,
                finding.id,
            )
        )
        policy.finding_operations.validate_participant_management(
            FindingOperationContext(
                case_lifecycle=review_case.lifecycle,
                current_finding_lifecycle=finding.lifecycle,
                participant_role_keys=participant_roles,
            )
        )
        self._require_role_kind(
            policy.finding_participant_role_specs,
            role_key,
            actor_kind,
        )
        return self._search_candidates(actor, actor_kind, search_text, limit)

    def search_action_assignee_candidates(
        self,
        actor: User,
        action_item_id: ActionItemId,
        *,
        role: AssignmentRole,
        actor_kind: ActorKind,
        search_text: str,
        limit: int,
    ) -> tuple[AssignmentCandidateView, ...]:
        action_item, finding, review_case, policy, context = self._action_policy_context(
            actor,
            action_item_id,
        )
        if not policy.authorization.allows(MANAGE_ACTION_ASSIGNEES_PERMISSION, context):
            raise ReviewAuthorizationError("Finding owner role required to manage ActionAssignee")
        assignee_roles = frozenset(
            item.role.value
            for item in self._repository.list_action_assignees(
                actor.organization_id,
                action_item.id,
            )
        )
        policy.action_operations.validate_assignee_management(
            ActionItemOperationContext(
                case_lifecycle=review_case.lifecycle,
                finding_lifecycle=finding.lifecycle,
                current_action_lifecycle=action_item.lifecycle,
                assignee_role_keys=assignee_roles,
            )
        )
        self._require_role_kind(policy.action_assignee_role_specs, role.value, actor_kind)
        return self._search_candidates(actor, actor_kind, search_text, limit)

    def search_action_transfer_candidates(
        self,
        actor: User,
        action_item_id: ActionItemId,
        *,
        search_text: str,
        limit: int,
    ) -> tuple[AssignmentCandidateView, ...]:
        action_item, finding, review_case, policy, context = self._action_policy_context(
            actor,
            action_item_id,
        )
        if not policy.authorization.allows(TRANSFER_AND_REOPEN_ACTION_PERMISSION, context):
            raise ReviewAuthorizationError(
                "Finding owner role required to transfer and reopen ActionItem"
            )
        assignees = self._repository.list_action_assignees(
            actor.organization_id,
            action_item.id,
        )
        policy.action_operations.validate_transfer_and_reopen_state(
            ActionItemOperationContext(
                case_lifecycle=review_case.lifecycle,
                finding_lifecycle=finding.lifecycle,
                current_action_lifecycle=action_item.lifecycle,
                has_active_assignee=self._rectification_service.has_active_executor(assignees),
            )
        )
        self._require_role_kind(
            policy.action_assignee_role_specs,
            AssignmentRole.PRIMARY.value,
            ActorKind.USER,
        )
        return self._search_candidates(actor, ActorKind.USER, search_text, limit)

    def list_finding_submissions(
        self,
        actor: User,
        finding_id: FindingId,
    ) -> tuple[Submission, ...]:
        finding = self._finding_service.get_finding(actor, finding_id)
        return self._repository.list_submissions(actor.organization_id, finding.id)

    def list_finding_activities(
        self,
        actor: User,
        finding_id: FindingId,
    ) -> tuple[ResourceActivityView, ...]:
        finding = self._finding_service.get_finding(actor, finding_id)
        records = tuple(
            self._session.scalars(
                select(ActivityRecord)
                .where(
                    ActivityRecord.organization_id == actor.organization_id,
                    ActivityRecord.finding_id == finding.id,
                    ActivityRecord.review_case_id.is_(None),
                    ActivityRecord.action_item_id.is_(None),
                    ActivityRecord.submission_id.is_(None),
                )
                .order_by(ActivityRecord.occurred_at.desc(), ActivityRecord.id.desc())
            )
        )
        return tuple(
            ResourceActivityView(
                id=record.id,
                subject_id=finding.id,
                event_type=record.event_type,
                actor_id=record.actor_id,
                occurred_at=record.occurred_at,
            )
            for record in records
        )

    def list_action_activities(
        self,
        actor: User,
        action_item_id: ActionItemId,
    ) -> tuple[ResourceActivityView, ...]:
        action_item = self._rectification_service.get_action_item(actor, action_item_id)
        records = tuple(
            self._session.scalars(
                select(ActivityRecord)
                .where(
                    ActivityRecord.organization_id == actor.organization_id,
                    ActivityRecord.action_item_id == action_item.id,
                    ActivityRecord.review_case_id.is_(None),
                    ActivityRecord.finding_id.is_(None),
                    ActivityRecord.submission_id.is_(None),
                )
                .order_by(ActivityRecord.occurred_at.desc(), ActivityRecord.id.desc())
            )
        )
        return tuple(
            ResourceActivityView(
                id=record.id,
                subject_id=action_item.id,
                event_type=record.event_type,
                actor_id=record.actor_id,
                occurred_at=record.occurred_at,
            )
            for record in records
        )

    def _finding_policy_context(
        self,
        actor: User,
        finding_id: FindingId,
    ) -> tuple[Finding, ReviewCase, ScenarioPolicy, AuthorizationContext]:
        finding = self._finding_service.get_finding(actor, finding_id)
        review_case = self._repository.get_case(actor.organization_id, finding.case_id)
        if review_case is None:
            raise LookupError("ReviewCase not found")
        policy = self._registry.get(review_case.scenario_key, review_case.scenario_version)
        context = build_rectification_authorization_context(
            self._repository,
            actor,
            review_case.id,
            finding_id=finding.id,
        )
        return finding, review_case, policy, context

    def _action_policy_context(
        self,
        actor: User,
        action_item_id: ActionItemId,
    ) -> tuple[ActionItem, Finding, ReviewCase, ScenarioPolicy, AuthorizationContext]:
        action_item = self._rectification_service.get_action_item(actor, action_item_id)
        finding = self._repository.get_finding(actor.organization_id, action_item.finding_id)
        if finding is None:
            raise LookupError("Finding not found")
        review_case = self._repository.get_case(actor.organization_id, finding.case_id)
        if review_case is None:
            raise LookupError("ReviewCase not found")
        policy = self._registry.get(review_case.scenario_key, review_case.scenario_version)
        context = build_rectification_authorization_context(
            self._repository,
            actor,
            review_case.id,
            finding_id=finding.id,
            action_item_id=action_item.id,
        )
        return action_item, finding, review_case, policy, context

    def _relationship_names(
        self,
        actor: User,
        relationships: tuple[FindingParticipant, ...] | tuple[ActionAssignee, ...],
    ) -> dict[tuple[ActorKind, UUID], str]:
        identities: set[tuple[ActorKind, UUID]] = set()
        for relationship in relationships:
            if isinstance(relationship, FindingParticipant):
                identities.add(self._participant_identity(relationship))
            else:
                identities.add(self._assignee_identity(relationship))

        user_ids = {actor_id for kind, actor_id in identities if kind is ActorKind.USER}
        department_ids = {
            actor_id for kind, actor_id in identities if kind is ActorKind.DEPARTMENT
        }
        names: dict[tuple[ActorKind, UUID], str] = {}
        if user_ids:
            users = tuple(
                self._session.scalars(
                    select(UserRecord).where(
                        UserRecord.organization_id == actor.organization_id,
                        UserRecord.id.in_(user_ids),
                    )
                )
            )
            names.update(
                {(ActorKind.USER, user.id): user.display_name for user in users}
            )
        if department_ids:
            departments = tuple(
                self._session.scalars(
                    select(DepartmentRecord).where(
                        DepartmentRecord.organization_id == actor.organization_id,
                        DepartmentRecord.id.in_(department_ids),
                    )
                )
            )
            names.update(
                {
                    (ActorKind.DEPARTMENT, department.id): department.name
                    for department in departments
                }
            )
        if set(names) != identities:
            raise LookupError("Relationship display actor not found")
        return names

    def _search_candidates(
        self,
        actor: User,
        actor_kind: ActorKind,
        search_text: str,
        limit: int,
    ) -> tuple[AssignmentCandidateView, ...]:
        normalized = search_text.strip()
        if len(normalized) < 2 or len(normalized) > 200:
            raise ValueError("candidate search requires 2 to 200 non-padding characters")
        if not 1 <= limit <= 20:
            raise ValueError("candidate search limit must be between 1 and 20")
        escaped = (
            normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        if actor_kind is ActorKind.USER:
            user_records = tuple(
                self._session.scalars(
                    select(UserRecord)
                    .where(
                        UserRecord.organization_id == actor.organization_id,
                        UserRecord.is_active.is_(True),
                        UserRecord.display_name.ilike(pattern, escape="\\"),
                    )
                    .order_by(UserRecord.display_name, UserRecord.id)
                    .limit(limit)
                )
            )
            return tuple(
                AssignmentCandidateView(
                    actor_kind=ActorKind.USER,
                    actor_id=record.id,
                    display_name=record.display_name,
                )
                for record in user_records
            )
        department_records = tuple(
            self._session.scalars(
                select(DepartmentRecord)
                .where(
                    DepartmentRecord.organization_id == actor.organization_id,
                    DepartmentRecord.is_active.is_(True),
                    DepartmentRecord.name.ilike(pattern, escape="\\"),
                )
                .order_by(DepartmentRecord.name, DepartmentRecord.id)
                .limit(limit)
            )
        )
        return tuple(
            AssignmentCandidateView(
                actor_kind=ActorKind.DEPARTMENT,
                actor_id=record.id,
                display_name=record.name,
            )
            for record in department_records
        )

    @staticmethod
    def _require_role_kind(
        specifications: tuple[RoleSpecification, ...],
        role_key: str,
        actor_kind: ActorKind,
    ) -> None:
        source = (
            PermissionSource.DIRECT
            if actor_kind is ActorKind.USER
            else PermissionSource.DEPARTMENT_MEMBERSHIP
        )
        grant = RoleGrant(role_key, actor_kind, source)
        if not any(specification.accepts_grant(grant) for specification in specifications):
            raise ValueError(
                f"Scenario does not allow relationship role {role_key!r} "
                f"for {actor_kind.value}"
            )

    @staticmethod
    def _participant_identity(
        participant: FindingParticipant,
    ) -> tuple[ActorKind, UUID]:
        if isinstance(participant.actor, UserActor):
            return ActorKind.USER, participant.actor.user_id
        return ActorKind.DEPARTMENT, participant.actor.department_id

    @staticmethod
    def _assignee_identity(assignee: ActionAssignee) -> tuple[ActorKind, UUID]:
        if isinstance(assignee.actor, UserActor):
            return ActorKind.USER, assignee.actor.user_id
        if isinstance(assignee.actor, DepartmentActor):
            return ActorKind.DEPARTMENT, assignee.actor.department_id
        raise TypeError("Unsupported ActionAssignee actor")
