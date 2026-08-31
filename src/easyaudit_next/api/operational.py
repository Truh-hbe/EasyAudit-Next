from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError, TimeoutError as SQLAlchemyTimeoutError

from easyaudit_next.api.dependencies import get_application_engine
from easyaudit_next.operations.metrics import metrics

operational_router = APIRouter()
_ROOT = Path(__file__).resolve().parents[3]


@operational_router.get(
    "/health/live",
    include_in_schema=False,
)
def health_live() -> dict[str, str]:
    return {"status": "alive"}


@operational_router.get(
    "/health/ready",
    include_in_schema=False,
)
def health_ready(
    engine: Engine = Depends(get_application_engine),
) -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            database_heads = set(MigrationContext.configure(connection).get_current_heads())
    except SQLAlchemyTimeoutError as exc:
        metrics.observe_database_failure("pool_timeout")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database readiness unavailable",
        ) from exc
    except SQLAlchemyError as exc:
        metrics.observe_database_failure("connect_failure")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database readiness unavailable",
        ) from exc

    expected_heads = _code_alembic_heads()
    if not database_heads or database_heads != expected_heads:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database schema is not ready",
        )
    return {"status": "ready"}


@operational_router.get(
    "/metrics",
    include_in_schema=False,
    response_class=PlainTextResponse,
)
def operational_metrics(
    engine: Engine = Depends(get_application_engine),
) -> PlainTextResponse:
    return PlainTextResponse(
        metrics.render_prometheus(engine),
        media_type="text/plain; version=0.0.4",
    )


def _code_alembic_heads() -> set[str]:
    config = Config(str(_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    return set(script.get_heads())
