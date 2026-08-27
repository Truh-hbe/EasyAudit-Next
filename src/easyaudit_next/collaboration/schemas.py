from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NudgeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    activity_id: UUID
    recipient_count: int
