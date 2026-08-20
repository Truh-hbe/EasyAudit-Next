from fastapi import FastAPI

from easyaudit_next.api.router import api_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="EasyAudit-Next API",
        version="0.0.0",
        description="Scenario-extensible review and remediation platform",
    )
    app.include_router(api_router)
    return app


app = create_app()
