from dataclasses import dataclass

from easyaudit_next.review_core.domain.ids import ActivityId
from easyaudit_next.review_core.domain.models import (
    ActionAssignee,
    Finding,
    FindingParticipant,
    CaseMember,
    Submission,
)


@dataclass(frozen=True, slots=True)
class CaseMemberAddedResult:
    """Scenario-neutral result for a CaseMember mutation and its exact Activity."""

    member: CaseMember
    activity_id: ActivityId


@dataclass(frozen=True, slots=True)
class FindingParticipantAddedResult:
    """Scenario-neutral result for a FindingParticipant mutation and its exact Activity."""

    participant: FindingParticipant
    activity_id: ActivityId


@dataclass(frozen=True, slots=True)
class ActionAssigneeAddedResult:
    """Scenario-neutral result for an ActionAssignee mutation and its exact Activity."""

    assignee: ActionAssignee
    activity_id: ActivityId


@dataclass(frozen=True, slots=True)
class RectificationSubmissionResult:
    """Scenario-neutral rectification result and the exact Activity it created."""

    submission: Submission
    finding: Finding
    activity_id: ActivityId
