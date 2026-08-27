from fastapi import APIRouter

from easyaudit_next.api.dependencies import BusinessIdentity, DatabaseSession
from easyaudit_next.composition import build_workbench_query_service
from easyaudit_next.workbench.schemas import WorkbenchResponse

workbench_router = APIRouter(prefix="/api/v1/me", tags=["workbench"])


@workbench_router.get(
    "/workbench",
    response_model=WorkbenchResponse,
    operation_id="getMyWorkbench",
)
def get_my_workbench(
    identity: BusinessIdentity,
    session: DatabaseSession,
) -> WorkbenchResponse:
    return build_workbench_query_service(session).get_workbench(identity.user)
