from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from easyaudit_next.notifications.models import (
    ActionItemNotificationSubject,
    FindingNotificationSubject,
    NotificationId,
    NotificationItem,
    ReviewCaseNotificationSubject,
)
from easyaudit_next.platform.domain.models import User
from easyaudit_next.review_core.domain.models import ScenarioKey, ScenarioVersion
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
VIEW_FINDING_PERMISSION = "view_finding"


@dataclass(frozen=True, slots=True)
class NotificationSubjectContext:
    """Titles and the recipient's roles, as the recipient may see them right now."""

    title: str
    finding_title: str | None
    case_title: str | None
    role_keys: tuple[str, ...]


class NotificationSubjectContextResolver:
    """Resolve what each Notification is about, gated by the recipient's *current* access.

    Delivered Notification rows are immutable and carry only generic copy. Titles are read
    here, at read time, and only for targets the recipient could open right now with the
    same rule the target's own GET endpoint applies (`view_case` / `view_finding` over the
    Case grants, plus this target's Finding / Action grants). A target that is not visible
    simply has no entry, so nothing about it leaks. A parent title (Finding for an Action,
    Case for a Finding or Action) is included only when that parent is itself visible.

    Queries are batched per page: a fixed number of statements regardless of page size.
    """

    def __init__(self, session: Session, registry: ScenarioRegistry) -> None:
        self._session = session
        self._registry = registry

    def resolve(
        self,
        recipient: User,
        items: Iterable[NotificationItem],
    ) -> dict[NotificationId, NotificationSubjectContext]:
        items = tuple(items)
        if not recipient.is_active:
            return {}
        case_ids: set[UUID] = set()
        finding_ids: set[UUID] = set()
        action_ids: set[UUID] = set()
        for item in items:
            subject = item.subject
            if isinstance(subject, ReviewCaseNotificationSubject):
                case_ids.add(subject.review_case_id)
            elif isinstance(subject, FindingNotificationSubject):
                finding_ids.add(subject.finding_id)
            elif isinstance(subject, ActionItemNotificationSubject):
                action_ids.add(subject.action_item_id)
        if not (case_ids or finding_ids or action_ids):
            return {}
        organization_id = recipient.organization_id

        actions = self._by_id(
            select(ActionItemRecord).where(
                ActionItemRecord.organization_id == organization_id,
                ActionItemRecord.id.in_(action_ids),
            )
            if action_ids
            else None
        )
        finding_ids.update(action.finding_id for action in actions.values())
        findings = self._by_id(
            select(FindingRecord).where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.id.in_(finding_ids),
            )
            if finding_ids
            else None
        )
        case_ids.update(finding.case_id for finding in findings.values())
        if not case_ids:
            return {}
        case_rows = self._session.execute(
            select(ReviewCaseRecord, ScenarioRecord.key, ScenarioVersionRecord.version)
            .join(
                ScenarioVersionRecord,
                (ScenarioVersionRecord.id == ReviewCaseRecord.scenario_version_id)
                & (ScenarioVersionRecord.organization_id == ReviewCaseRecord.organization_id),
            )
            .join(
                ScenarioRecord,
                (ScenarioRecord.id == ScenarioVersionRecord.scenario_id)
                & (ScenarioRecord.organization_id == ScenarioVersionRecord.organization_id),
            )
            .where(
                ReviewCaseRecord.organization_id == organization_id,
                ReviewCaseRecord.id.in_(case_ids),
            )
        ).all()
        cases = {row[0].id: row[0] for row in case_rows}
        policies: dict[UUID, ScenarioPolicy] = {}
        for review_case, scenario_key, scenario_version in case_rows:
            try:
                policies[review_case.id] = self._registry.get(
                    ScenarioKey(scenario_key),
                    ScenarioVersion(scenario_version),
                )
            except LookupError:
                continue  # Unknown Scenario version: nothing can be judged visible.

        case_grants: dict[UUID, set[RoleGrant]] = defaultdict(set)
        for member in self._session.scalars(
            select(CaseMemberRecord).where(
                CaseMemberRecord.organization_id == organization_id,
                CaseMemberRecord.user_id == recipient.id,
                CaseMemberRecord.case_id.in_(cases),
            )
        ):
            case_grants[member.case_id].add(
                RoleGrant(member.role_key, ActorKind.USER, PermissionSource.DIRECT)
            )

        # Case-wide finding grants (the Case context) and per-finding grants (the Finding
        # context) come from one query; a Finding context never sees another Finding's grants.
        finding_grants: dict[UUID, set[RoleGrant]] = defaultdict(set)
        finding_grants_by_case: dict[UUID, set[RoleGrant]] = defaultdict(set)
        participant_filter = FindingParticipantRecord.user_id == recipient.id
        if recipient.primary_department_id is not None:
            participant_filter = or_(
                participant_filter,
                FindingParticipantRecord.department_id == recipient.primary_department_id,
            )
        for participant, participant_case_id in self._session.execute(
            select(FindingParticipantRecord, FindingRecord.case_id)
            .join(
                FindingRecord,
                (FindingRecord.id == FindingParticipantRecord.finding_id)
                & (FindingRecord.organization_id == FindingParticipantRecord.organization_id),
            )
            .where(
                FindingParticipantRecord.organization_id == organization_id,
                FindingRecord.case_id.in_(cases),
                participant_filter,
            )
        ):
            grant = _grant(participant.role_key, participant.user_id)
            finding_grants[participant.finding_id].add(grant)
            finding_grants_by_case[participant_case_id].add(grant)

        action_grants: dict[UUID, set[RoleGrant]] = defaultdict(set)
        if actions:
            assignee_filter = ActionAssigneeRecord.user_id == recipient.id
            if recipient.primary_department_id is not None:
                assignee_filter = or_(
                    assignee_filter,
                    ActionAssigneeRecord.department_id == recipient.primary_department_id,
                )
            for assignee in self._session.scalars(
                select(ActionAssigneeRecord).where(
                    ActionAssigneeRecord.organization_id == organization_id,
                    ActionAssigneeRecord.action_item_id.in_(actions),
                    assignee_filter,
                )
            ):
                action_grants[assignee.action_item_id].add(_grant(assignee.role, assignee.user_id))

        def context(
            case_id: UUID,
            *,
            case_wide_findings: bool = False,
            finding_id: UUID | None = None,
            action_id: UUID | None = None,
        ) -> AuthorizationContext:
            if case_wide_findings:
                finding_set = finding_grants_by_case.get(case_id, set())
            else:
                finding_set = finding_grants.get(finding_id, set()) if finding_id else set()
            return AuthorizationContext(
                is_active_organization_user=recipient.is_active,
                case_role_grants=frozenset(case_grants.get(case_id, set())),
                finding_role_grants=frozenset(finding_set),
                action_role_grants=frozenset(
                    action_grants.get(action_id, set()) if action_id else set()
                ),
            )

        def case_visible(case_id: UUID) -> bool:
            policy = policies.get(case_id)
            return policy is not None and policy.authorization.allows(
                VIEW_CASE_PERMISSION,
                context(case_id, case_wide_findings=True),
            )

        def finding_visible(finding: FindingRecord) -> bool:
            policy = policies.get(finding.case_id)
            return policy is not None and policy.authorization.allows(
                VIEW_FINDING_PERMISSION,
                context(finding.case_id, finding_id=finding.id),
            )

        resolved: dict[NotificationId, NotificationSubjectContext] = {}
        for item in items:
            subject = item.subject
            if isinstance(subject, ReviewCaseNotificationSubject):
                review_case = cases.get(subject.review_case_id)
                if review_case is None or not case_visible(review_case.id):
                    continue
                resolved[item.id] = NotificationSubjectContext(
                    title=review_case.title,
                    finding_title=None,
                    case_title=None,
                    role_keys=_role_keys(case_grants.get(review_case.id, ())),
                )
            elif isinstance(subject, FindingNotificationSubject):
                finding = findings.get(subject.finding_id)
                if finding is None or not finding_visible(finding):
                    continue
                resolved[item.id] = NotificationSubjectContext(
                    title=finding.title,
                    finding_title=None,
                    case_title=(
                        cases[finding.case_id].title if case_visible(finding.case_id) else None
                    ),
                    role_keys=_role_keys(finding_grants.get(finding.id, ())),
                )
            elif isinstance(subject, ActionItemNotificationSubject):
                action = actions.get(subject.action_item_id)
                if action is None:
                    continue
                parent = findings.get(action.finding_id)
                policy = None if parent is None else policies.get(parent.case_id)
                if parent is None or policy is None:
                    continue
                if not policy.authorization.allows(
                    VIEW_FINDING_PERMISSION,
                    context(parent.case_id, finding_id=parent.id, action_id=action.id),
                ):
                    continue
                resolved[item.id] = NotificationSubjectContext(
                    title=action.title,
                    finding_title=parent.title if finding_visible(parent) else None,
                    case_title=(
                        cases[parent.case_id].title if case_visible(parent.case_id) else None
                    ),
                    role_keys=_role_keys(action_grants.get(action.id, ())),
                )
        return resolved

    def _by_id[R: (ActionItemRecord, FindingRecord)](
        self,
        statement: Select[tuple[R]] | None,
    ) -> dict[UUID, R]:
        if statement is None:
            return {}
        return {record.id: record for record in self._session.scalars(statement)}


def _grant(role_key: str, user_id: UUID | None) -> RoleGrant:
    if user_id is not None:
        return RoleGrant(role_key, ActorKind.USER, PermissionSource.DIRECT)
    return RoleGrant(role_key, ActorKind.DEPARTMENT, PermissionSource.DEPARTMENT_MEMBERSHIP)


def _role_keys(grants: Iterable[RoleGrant]) -> tuple[str, ...]:
    return tuple(sorted({grant.role_key for grant in grants}))
