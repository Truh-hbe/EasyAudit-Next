from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CaseMemberViewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: UUID
    user_id: UUID
    role_key: str
    joined_at: datetime
    display_name: str


class ReviewCaseActivityResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    subject_type: Literal["review_case"] = "review_case"
    subject_id: UUID
    event_type: str
    actor_id: UUID | None
    occurred_at: datetime
