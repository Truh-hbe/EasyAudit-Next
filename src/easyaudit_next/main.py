from fastapi import FastAPI

from easyaudit_next.api.review_findings import review_findings_router
from easyaudit_next.api.review_planning import review_planning_router
from easyaudit_next.api.review_rectification import review_rectification_router
from easyaudit_next.api.review_verification import review_verification_router
from easyaudit_next.api.router import api_router
from easyaudit_next.management.api import management_router
from easyaudit_next.notifications.api import notification_router
from easyaudit_next.workbench.api import workbench_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="EasyAudit-Next API",
        version="0.0.0",
        description="Scenario-extensible review and remediation platform",
    )
    app.include_router(api_router)
    app.include_router(review_planning_router)
    app.include_router(review_findings_router)
    app.include_router(review_rectification_router)
    app.include_router(review_verification_router)
    app.include_router(workbench_router)
    app.include_router(notification_router)
    app.include_router(management_router)
    return app


app = create_app()
