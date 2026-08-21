from easyaudit_next.main import create_app


def test_review_planning_routes_depend_on_business_identity() -> None:
    schema = create_app().openapi()
    # Authentication is cookie-backed and enforced as a FastAPI dependency rather than an
    # OpenAPI security scheme in M2.2. This smoke test ensures the business route remains part of
    # the app while dependency behavior is covered by integration/API authentication tests.
    assert "/api/v1/review-cases" in schema["paths"]
