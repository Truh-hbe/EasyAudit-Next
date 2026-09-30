from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from easyaudit_next.api.contracts import LiveResponse, ReadyChecks, ReadyResponse
from easyaudit_next.infrastructure.readiness import (
    log_failure,
    run_readiness,
)
from easyaudit_next.platform.settings import get_settings

# Mounted at the root, not under /api/v1: the gateway only forwards /api/v1/* to the API,
# so these endpoints are not reachable from outside.
health_router = APIRouter(prefix="/health", tags=["system"])


# Both handlers are `async def` on purpose: they never occupy the AnyIO thread pool.
@health_router.get("/live", response_model=LiveResponse, operation_id="getHealthLive")
async def get_health_live() -> LiveResponse:
    """Process is up. Touches neither the database nor any external dependency."""
    return LiveResponse(status="ok")


@health_router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse}},
    operation_id="getHealthReady",
)
async def get_health_ready(request: Request) -> JSONResponse:
    """Database reachable, alembic at head, required configuration present."""
    result = await run_readiness(
        get_settings(),
        getattr(request.app.state, "expected_head", None),  # set by lifespan; None = unavailable
        request.app.state,
    )
    for failure in result.failures:
        log_failure(failure)  # logged in this request's context, so it carries its request_id
    ready = all(value == "ok" for value in result.checks.values())
    body = ReadyResponse(status="ok" if ready else "fail", checks=ReadyChecks(**result.checks))
    return JSONResponse(body.model_dump(), status_code=200 if ready else 503)
