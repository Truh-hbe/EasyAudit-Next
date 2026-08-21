from collections.abc import Iterable
from uuid import UUID

from easyaudit_next.review_core.domain.models import (
    ActionAssignee,
    DepartmentActor,
    Finding,
    FindingParticipant,
    ReviewCase,
    ReviewPlan,
    UserActor,
)


def assert_plan_contains_case(plan: ReviewPlan, review_case: ReviewCase) -> None:
    if review_case.plan_id != plan.id:
        raise ValueError("ReviewCase does not belong to ReviewPlan")
    if review_case.organization_id != plan.organization_id:
        raise ValueError("ReviewPlan and ReviewCase must belong to the same organization")


def assert_finding_belongs_to_case(finding: Finding, review_case: ReviewCase) -> None:
    if finding.case_id != review_case.id:
        raise ValueError("Finding does not belong to ReviewCase")


def _actor_key(actor: UserActor | DepartmentActor) -> tuple[str, UUID]:
    if isinstance(actor, UserActor):
        return ("user", actor.user_id)
    return ("department", actor.department_id)


def assert_unique_finding_participants(
    participants: Iterable[FindingParticipant],
) -> None:
    keys: set[tuple[str, str, UUID, str]] = set()
    for participant in participants:
        actor_type, actor_id = _actor_key(participant.actor)
        key = (participant.finding_id, actor_type, actor_id, participant.role_key)
        if key in keys:
            raise ValueError(f"Duplicate FindingParticipant: {key}")
        keys.add(key)


def assert_unique_action_assignees(assignees: Iterable[ActionAssignee]) -> None:
    keys: set[tuple[str, str, UUID, str]] = set()
    for assignee in assignees:
        actor_type, actor_id = _actor_key(assignee.actor)
        key = (assignee.action_item_id, actor_type, actor_id, assignee.role)
        if key in keys:
            raise ValueError(f"Duplicate ActionAssignee: {key}")
        keys.add(key)
