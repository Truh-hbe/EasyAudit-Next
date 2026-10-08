import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from easyaudit_next.api.errors import (
    RULE_ERROR_RESPONSES,
    CodedHTTPException,
    coded_http_exception_handler,
    request_validation_handler,
    rule_violation_handler,
)
from easyaudit_next.api.health import health_router
from easyaudit_next.api.review_evidence_downloads import review_evidence_download_router
from easyaudit_next.api.review_evidence_uploads import review_evidence_upload_router
from easyaudit_next.api.review_findings import review_findings_router
from easyaudit_next.api.review_planning import review_planning_router
from easyaudit_next.api.review_rectification import review_rectification_router
from easyaudit_next.api.review_resource_queries import review_resource_query_router
from easyaudit_next.api.review_verification import review_verification_router
from easyaudit_next.api.router import api_router
from easyaudit_next.collaboration.api import collaboration_router
from easyaudit_next.composition import build_evidence_object_store, build_evidence_upload_policy
from easyaudit_next.infrastructure.observability import (
    APP_LOGGER,
    RequestContextMiddleware,
    describe_exception,
)
from easyaudit_next.infrastructure.readiness import load_expected_head
from easyaudit_next.management.api import management_router
from easyaudit_next.notifications.api import notification_router
from easyaudit_next.platform.settings import get_settings
from easyaudit_next.review_core.application.evidence_storage import (
    EvidenceObjectStore,
    ObjectStoreNotConfiguredError,
)
from easyaudit_next.rules import RuleViolation
from easyaudit_next.workbench.api import workbench_router


async def _load_evidence_store() -> EvidenceObjectStore | None:
    """Built once, off the event loop (it reads the credential files). Without a usable
    configuration uploads answer 503 and /health/ready reports object_storage as fail."""
    try:
        return await asyncio.to_thread(build_evidence_object_store, get_settings())
    except ObjectStoreNotConfiguredError as exc:
        APP_LOGGER.warning(
            "evidence_store_unavailable",
            extra={
                "fields": {"component": "object_storage", "reason": "not_configured"},
                "exception_details": describe_exception(exc),
            },
        )
        return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Read the expected alembic head once at startup, off the event loop. If it cannot be read
    # (logged at ERROR), /health/ready reports migrations as failed until the process restarts.
    app.state.expected_head = await load_expected_head()
    # Fail fast on an invalid EVIDENCE_* policy instead of answering 500 to the first upload.
    build_evidence_upload_policy(get_settings())
    app.state.evidence_store = await _load_evidence_store()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="EasyAudit-Next API",
        version="0.0.0",
        lifespan=lifespan,
        description="Scenario-extensible review and remediation platform",
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(RuleViolation, rule_violation_handler)
    app.add_exception_handler(CodedHTTPException, coded_http_exception_handler)
    app.include_router(health_router)
    app.include_router(api_router, responses=RULE_ERROR_RESPONSES)
    app.include_router(review_planning_router, responses=RULE_ERROR_RESPONSES)
    app.include_router(review_findings_router, responses=RULE_ERROR_RESPONSES)
    app.include_router(review_rectification_router, responses=RULE_ERROR_RESPONSES)
    app.include_router(review_evidence_upload_router, responses=RULE_ERROR_RESPONSES)
    app.include_router(review_evidence_download_router, responses=RULE_ERROR_RESPONSES)
    app.include_router(review_verification_router, responses=RULE_ERROR_RESPONSES)
    app.include_router(review_resource_query_router, responses=RULE_ERROR_RESPONSES)
    app.include_router(workbench_router, responses=RULE_ERROR_RESPONSES)
    app.include_router(notification_router, responses=RULE_ERROR_RESPONSES)
    app.include_router(management_router, responses=RULE_ERROR_RESPONSES)
    app.include_router(collaboration_router, responses=RULE_ERROR_RESPONSES)
    return app


app = create_app()
