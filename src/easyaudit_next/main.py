from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from easyaudit_next.api.health import health_router
from easyaudit_next.api.review_findings import review_findings_router
from easyaudit_next.api.review_planning import review_planning_router
from easyaudit_next.api.review_rectification import review_rectification_router
from easyaudit_next.api.review_resource_queries import review_resource_query_router
from easyaudit_next.api.review_verification import review_verification_router
from easyaudit_next.api.router import api_router
from easyaudit_next.collaboration.api import collaboration_router
from easyaudit_next.infrastructure.observability import APP_LOGGER, RequestContextMiddleware
from easyaudit_next.infrastructure.readiness import get_expected_head
from easyaudit_next.management.api import management_router
from easyaudit_next.notifications.api import notification_router
from easyaudit_next.workbench.api import workbench_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Compute (and cache) the expected alembic head once at startup. Failure is not fatal:
    # /health/ready then reports migrations as failed and logs why.
    try:
        get_expected_head()
    except Exception as exc:
        APP_LOGGER.warning("expected_head_unavailable", exc_info=exc)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="EasyAudit-Next API",
        version="0.0.0",
        lifespan=lifespan,
        description="Scenario-extensible review and remediation platform",
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health_router)
    app.include_router(api_router)
    app.include_router(review_planning_router)
    app.include_router(review_findings_router)
    app.include_router(review_rectification_router)
    app.include_router(review_verification_router)
    app.include_router(review_resource_query_router)
    app.include_router(workbench_router)
    app.include_router(notification_router)
    app.include_router(management_router)
    app.include_router(collaboration_router)
    return app


app = create_app()
