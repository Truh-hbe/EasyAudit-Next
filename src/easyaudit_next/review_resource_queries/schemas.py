from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from easyaudit_next.review_core.domain.models import AssignmentRole
from easyaudit_next.review_core.domain.scenario_capabilities import ActorKind


class RelationshipActorViewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    actor_kind: ActorKind
    actor_id: UUID
    display_name: str


class FindingParticipantViewResponse(RelationshipActorViewResponse):
    finding_id: UUID
    role_key: str
    assigned_at: datetime


class ActionAssigneeViewResponse(RelationshipActorViewResponse):
    action_item_id: UUID
    role: AssignmentRole
    assigned_at: datetime


class AssignmentCandidateResponse(RelationshipActorViewResponse):
    pass


class FindingActivityResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    subject_type: Literal["finding"] = "finding"
    subject_id: UUID
    event_type: str
    actor_id: UUID | None
    occurred_at: datetime


class ActionItemActivityResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    subject_type: Literal["action_item"] = "action_item"
    subject_id: UUID
    event_type: str
    actor_id: UUID | None
    occurred_at: datetime
