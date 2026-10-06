"""Every route that waits on the Case lock maps ConcurrentCaseTransitionError to 409.

The service is replaced by a stub that raises it from whatever method the route calls.
"""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from easyaudit_next.api import (
    review_evidence_uploads,
    review_findings,
    review_planning,
    review_rectification,
    review_verification,
)
from easyaudit_next.api.dependencies import get_database_session, require_business_identity
from easyaudit_next.main import create_app
from easyaudit_next.review_core.application.authorization import ConcurrentCaseTransitionError

ID = uuid4()
OTHER = uuid4()

ROUTES: list[tuple[Any, str, str, str, dict[str, Any]]] = [
    (
        review_findings,
        "build_finding_lifecycle_service",
        "POST",
        f"/api/v1/review-cases/{ID}/findings",
        {"title": "t", "severity": "high", "scenario_data": {}},
    ),
    (
        review_findings,
        "build_finding_lifecycle_service",
        "POST",
        f"/api/v1/findings/{ID}/participants",
        {"actor_kind": "user", "actor_id": str(OTHER), "role_key": "owner"},
    ),
    (
        review_findings,
        "build_finding_lifecycle_service",
        "POST",
        f"/api/v1/findings/{ID}/transitions",
        {"action": "void", "reason": "dup"},
    ),
    (
        review_rectification,
        "build_rectification_service",
        "POST",
        f"/api/v1/findings/{ID}/actions",
        {"title": "fix"},
    ),
    (
        review_rectification,
        "build_rectification_service",
        "POST",
        f"/api/v1/action-items/{ID}/assignees",
        {"actor_kind": "user", "actor_id": str(OTHER), "role": "primary"},
    ),
    (
        review_rectification,
        "build_rectification_service",
        "POST",
        f"/api/v1/action-items/{ID}/transitions",
        {"action": "start"},
    ),
    (
        review_rectification,
        "build_rectification_service",
        "POST",
        f"/api/v1/findings/{ID}/rectification-submissions",
        {"action": "submit_plan", "payload": {}},
    ),
    (
        review_verification,
        "build_verification_closure_service",
        "POST",
        f"/api/v1/findings/{ID}/verification-submissions",
        {"action": "approve", "payload": {}},
    ),
    (
        review_verification,
        "build_verification_closure_service",
        "POST",
        f"/api/v1/findings/{ID}/reopen",
        {"reason": "again"},
    ),
    (
        review_planning,
        "build_review_planning_service",
        "POST",
        f"/api/v1/review-cases/{ID}/transitions",
        {"action": "schedule"},
    ),
]


class _RaisingService:
    def __getattr__(self, name: str) -> Any:
        def raise_conflict(*args: object, **kwargs: object) -> None:
            raise ConcurrentCaseTransitionError("Concurrent ReviewCase transition")

        return raise_conflict


@pytest.mark.parametrize(
    ("module", "builder", "method", "path", "body"),
    ROUTES,
    ids=[route[3].replace(str(ID), "{id}") for route in ROUTES],
)
def test_case_lock_conflict_is_409(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    builder: str,
    method: str,
    path: str,
    body: dict[str, Any],
) -> None:
    monkeypatch.setattr(module, builder, lambda session: _RaisingService())
    app = create_app()
    app.dependency_overrides[require_business_identity] = lambda: SimpleNamespace(user=object())
    app.dependency_overrides[get_database_session] = lambda: object()

    response = TestClient(app).request(method, path, json=body)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Concurrent ReviewCase transition"


def test_evidence_upload_business_errors_include_case_lock_conflict() -> None:
    assert ConcurrentCaseTransitionError in review_evidence_uploads._BUSINESS_ERRORS
    with pytest.raises(Exception) as caught:
        review_evidence_uploads._raise_api_error(ConcurrentCaseTransitionError("x"))
    assert getattr(caught.value, "status_code", None) == 409
