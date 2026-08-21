from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]
    stage: Literal["M1.1"]


class DomainModelResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: Literal["M1.1"]
    concepts: tuple[str, ...]
    backend: Literal["Python/FastAPI"]
    next: str
