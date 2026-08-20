from fastapi import APIRouter

from easyaudit_next.api.contracts import DomainModelResponse, HealthResponse

api_router = APIRouter()

CORE_CONCEPTS = (
    "Scenario",
    "ReviewPlan",
    "ReviewCase",
    "Finding",
    "ActionItem",
    "CaseMember",
    "FindingParticipant",
    "ActionAssignee",
    "Activity",
    "Submission",
)


@api_router.get(
    "/health",
    response_model=HealthResponse,
    operation_id="getHealth",
    tags=["system"],
)
def get_health() -> HealthResponse:
    return HealthResponse(status="ok", stage="M0.1")


@api_router.get(
    "/api/v1/meta/domain-model",
    response_model=DomainModelResponse,
    operation_id="getDomainModel",
    tags=["meta"],
)
def get_domain_model() -> DomainModelResponse:
    return DomainModelResponse(
        stage="M0.1",
        concepts=CORE_CONCEPTS,
        backend="Python/FastAPI",
        next="M1 Identity & Organization and first domain migration",
    )
