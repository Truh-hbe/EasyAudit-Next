from pydantic import BaseModel, ConfigDict, Field

from easyaudit_next.api.review_contracts import FindingResponse, SubmissionResponse


class VerificationSubmissionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=100)
    payload: dict[str, object] = Field(default_factory=dict)


class VerificationSubmissionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    submission: SubmissionResponse
    finding: FindingResponse


class FindingReopenRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2_000)
