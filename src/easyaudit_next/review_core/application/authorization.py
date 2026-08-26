from easyaudit_next.platform.domain.models import User
from easyaudit_next.review_core.domain.ids import ActionItemId, FindingId, ReviewCaseId
from easyaudit_next.review_core.domain.models import DepartmentActor, UserActor
from easyaudit_next.review_core.domain.repositories import (
    RectificationRepository,
    ReviewCoreRepository,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActorKind,
    AuthorizationContext,
    PermissionSource,
    RoleGrant,
)


def build_authorization_context(
    repository: ReviewCoreRepository,
    actor: User,
    case_id: ReviewCaseId,
    *,
    finding_id: FindingId | None = None,
) -> AuthorizationContext:
    """Derive Case/Finding Scenario grants from persisted relationships."""

    case_grants = frozenset(
        RoleGrant(
            role_key=member.role_key,
            actor_kind=ActorKind.USER,
            source=PermissionSource.DIRECT,
        )
        for member in repository.list_case_members(actor.organization_id, case_id)
        if member.user_id == actor.id
    )

    finding_ids = (
        (finding_id,)
        if finding_id is not None
        else tuple(
            finding.id for finding in repository.list_findings(actor.organization_id, case_id)
        )
    )
    finding_grants: set[RoleGrant] = set()
    for current_finding_id in finding_ids:
        for participant in repository.list_finding_participants(
            actor.organization_id,
            current_finding_id,
        ):
            if isinstance(participant.actor, UserActor):
                if participant.actor.user_id == actor.id:
                    finding_grants.add(
                        RoleGrant(
                            role_key=participant.role_key,
                            actor_kind=ActorKind.USER,
                            source=PermissionSource.DIRECT,
                        )
                    )
            elif participant.actor.department_id == actor.primary_department_id:
                finding_grants.add(
                    RoleGrant(
                        role_key=participant.role_key,
                        actor_kind=ActorKind.DEPARTMENT,
                        source=PermissionSource.DEPARTMENT_MEMBERSHIP,
                    )
                )

    return AuthorizationContext(
        is_active_organization_user=actor.is_active,
        case_role_grants=case_grants,
        finding_role_grants=frozenset(finding_grants),
    )


def build_rectification_authorization_context(
    repository: RectificationRepository,
    actor: User,
    case_id: ReviewCaseId,
    *,
    finding_id: FindingId | None = None,
    action_item_id: ActionItemId | None = None,
) -> AuthorizationContext:
    """Add ActionAssignee grants only for services that own the M2.4 capability surface."""

    base = build_authorization_context(
        repository,
        actor,
        case_id,
        finding_id=finding_id,
    )
    finding_ids = (
        (finding_id,)
        if finding_id is not None
        else tuple(
            finding.id for finding in repository.list_findings(actor.organization_id, case_id)
        )
    )
    action_ids = (
        (action_item_id,)
        if action_item_id is not None
        else tuple(
            action.id
            for current_finding_id in finding_ids
            for action in repository.list_action_items(
                actor.organization_id,
                current_finding_id,
            )
        )
    )
    action_grants: set[RoleGrant] = set()
    for current_action_id in action_ids:
        for assignee in repository.list_action_assignees(
            actor.organization_id,
            current_action_id,
        ):
            if isinstance(assignee.actor, UserActor):
                if assignee.actor.user_id == actor.id:
                    action_grants.add(
                        RoleGrant(
                            role_key=assignee.role.value,
                            actor_kind=ActorKind.USER,
                            source=PermissionSource.DIRECT,
                        )
                    )
            elif isinstance(assignee.actor, DepartmentActor) and (
                assignee.actor.department_id == actor.primary_department_id
            ):
                action_grants.add(
                    RoleGrant(
                        role_key=assignee.role.value,
                        actor_kind=ActorKind.DEPARTMENT,
                        source=PermissionSource.DEPARTMENT_MEMBERSHIP,
                    )
                )

    return AuthorizationContext(
        is_active_organization_user=base.is_active_organization_user,
        case_role_grants=base.case_role_grants,
        finding_role_grants=base.finding_role_grants,
        action_role_grants=frozenset(action_grants),
    )
