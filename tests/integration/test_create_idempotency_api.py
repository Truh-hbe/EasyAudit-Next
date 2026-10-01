"""Pilot-3: Idempotency-Key semantics of POST /review-plans and POST /review-cases."""

from uuid import uuid4

import pytest
from sqlalchemy import Engine

from tests.integration.create_idempotency_support import (
    CASE_BODY,
    clone,
    count_activities,
    count_cases,
    count_plans,
    count_records,
    login,
    postgres_engine,
    requires_postgres,
    seed_org,
)

pytestmark = requires_postgres
__all__ = ["postgres_engine"]

REPLAYED = "idempotent-replayed"


def _key() -> dict[str, str]:
    return {"Idempotency-Key": f"k-{uuid4()}"}


def test_plan_same_key_same_payload_returns_the_first_plan(postgres_engine: Engine) -> None:
    organization_id, [(_, name)] = seed_org(postgres_engine)
    client = login(postgres_engine, name)
    headers = _key()
    body = {"title": f"plan-{uuid4()}"}

    first = client.post("/api/v1/review-plans", json=body, headers=headers)
    second = client.post("/api/v1/review-plans", json=body, headers=headers)

    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    assert REPLAYED not in first.headers
    assert second.headers[REPLAYED] == "true"
    assert count_plans(postgres_engine, organization_id, body["title"]) == 1
    assert count_records(postgres_engine, organization_id) == 1


def test_case_replay_returns_current_representation_without_new_activity(
    postgres_engine: Engine,
) -> None:
    organization_id, [(_, name)] = seed_org(postgres_engine)
    client = login(postgres_engine, name)
    headers = _key()
    body = {**CASE_BODY, "title": f"case-{uuid4()}"}

    first = client.post("/api/v1/review-cases", json=body, headers=headers)
    assert first.status_code == 201
    activities = count_activities(postgres_engine, organization_id)
    assert activities == 1

    case_id = first.json()["id"]
    transition = client.post(
        f"/api/v1/review-cases/{case_id}/transitions", json={"action": "schedule"}
    )
    assert transition.status_code == 200
    activities = count_activities(postgres_engine, organization_id)

    second = client.post("/api/v1/review-cases", json=body, headers=headers)

    assert second.status_code == 201
    assert second.headers[REPLAYED] == "true"
    assert second.json()["id"] == case_id
    assert second.json()["lifecycle"] == "scheduled"  # current state, not a snapshot
    assert count_activities(postgres_engine, organization_id) == activities
    assert count_cases(postgres_engine, organization_id, body["title"]) == 1


def test_fingerprint_ignores_key_order_and_datetime_spelling(postgres_engine: Engine) -> None:
    organization_id, [(_, name)] = seed_org(postgres_engine)
    client = login(postgres_engine, name)
    headers = _key()
    title = f"plan-{uuid4()}"

    first = client.post(
        "/api/v1/review-plans",
        json={"title": title, "planned_start_at": "2026-10-01T08:00:00+08:00"},
        headers=headers,
    )
    second = client.post(
        "/api/v1/review-plans",
        json={"planned_end_at": None, "planned_start_at": "2026-10-01T00:00:00Z", "title": title},
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.headers[REPLAYED] == "true"
    assert count_plans(postgres_engine, organization_id, title) == 1


@pytest.mark.parametrize(
    "changed",
    [{"title": "other"}, {"planned_end_at": "2030-01-01T00:00:00Z"}],
)
def test_plan_same_key_different_payload_is_409(postgres_engine: Engine, changed: dict) -> None:
    organization_id, [(_, name)] = seed_org(postgres_engine)
    client = login(postgres_engine, name)
    headers = _key()
    title = f"plan-{uuid4()}"
    first = client.post("/api/v1/review-plans", json={"title": title}, headers=headers)
    assert first.status_code == 201

    conflict = client.post(
        "/api/v1/review-plans", json={"title": title, **changed}, headers=headers
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Idempotency-Key reused with a different request"
    assert count_plans(postgres_engine, organization_id, "other") == 0


def test_case_same_key_different_payload_is_409_and_creates_nothing(
    postgres_engine: Engine,
) -> None:
    organization_id, [(_, name)] = seed_org(postgres_engine)
    client = login(postgres_engine, name)
    headers = _key()
    title = f"case-{uuid4()}"
    assert client.post(
        "/api/v1/review-cases", json={**CASE_BODY, "title": title}, headers=headers
    ).status_code == 201
    activities = count_activities(postgres_engine, organization_id)

    conflict = client.post(
        "/api/v1/review-cases", json={**CASE_BODY, "title": title + "-b"}, headers=headers
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Idempotency-Key reused with a different request"
    assert count_cases(postgres_engine, organization_id, title + "-b") == 0
    assert count_activities(postgres_engine, organization_id) == activities


def test_scopes_are_independent_by_actor_operation_and_organization(
    postgres_engine: Engine,
) -> None:
    organization_id, [(_, name_a), (_, name_b)] = seed_org(postgres_engine, users=2)
    other_org, [(_, name_c)] = seed_org(postgres_engine)
    client_a = login(postgres_engine, name_a)
    client_b = login(postgres_engine, name_b)
    client_c = login(postgres_engine, name_c)
    headers = _key()
    title = f"shared-{uuid4()}"
    plan_body = {"title": title}
    case_body = {**CASE_BODY, "title": title}

    plan_a = client_a.post("/api/v1/review-plans", json=plan_body, headers=headers)
    # Same key, different actor / organization / operation: all are fresh creations.
    plan_b = client_b.post("/api/v1/review-plans", json=plan_body, headers=headers)
    plan_c = client_c.post("/api/v1/review-plans", json=plan_body, headers=headers)
    case_a = client_a.post("/api/v1/review-cases", json=case_body, headers=headers)

    responses = (plan_a, plan_b, plan_c, case_a)
    assert [r.status_code for r in responses] == [201, 201, 201, 201]
    assert all(REPLAYED not in r.headers for r in responses)
    assert len({r.json()["id"] for r in responses}) == 4
    assert count_plans(postgres_engine, organization_id, title) == 2
    assert count_plans(postgres_engine, other_org, title) == 1
    # And each scope still replays by itself.
    replay_c = client_c.post("/api/v1/review-plans", json=plan_body, headers=headers)
    assert replay_c.json()["id"] == plan_c.json()["id"]
    assert replay_c.headers[REPLAYED] == "true"


def test_replay_is_still_read_authorized(postgres_engine: Engine) -> None:
    """The claim sits in the actor's own scope, and the resource is re-read with the actor."""

    organization_id, [(_, name)] = seed_org(postgres_engine)
    client = login(postgres_engine, name)
    headers = _key()
    body = {**CASE_BODY, "title": f"case-{uuid4()}"}
    created = client.post("/api/v1/review-cases", json=body, headers=headers)
    assert created.status_code == 201

    # Remove the creator's memberships: the Case is no longer visible to them.
    from sqlalchemy import delete, text
    from sqlalchemy.orm import Session

    from easyaudit_next.review_core.persistence.models import CaseMemberRecord

    with Session(postgres_engine) as session, session.begin():
        session.execute(text("ALTER TABLE case_members DISABLE TRIGGER USER"))
        session.execute(
            delete(CaseMemberRecord).where(CaseMemberRecord.organization_id == organization_id)
        )
        session.execute(text("ALTER TABLE case_members ENABLE TRIGGER USER"))

    replay = client.post("/api/v1/review-cases", json=body, headers=headers)

    assert replay.status_code in (403, 404)
    assert REPLAYED not in replay.headers


def test_no_header_keeps_current_behaviour(postgres_engine: Engine) -> None:
    organization_id, [(_, name)] = seed_org(postgres_engine)
    client = login(postgres_engine, name)
    title = f"plan-{uuid4()}"

    first = client.post("/api/v1/review-plans", json={"title": title})
    second = client.post("/api/v1/review-plans", json={"title": title})

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert REPLAYED not in second.headers
    assert count_plans(postgres_engine, organization_id, title) == 2
    assert count_records(postgres_engine, organization_id) == 0


@pytest.mark.parametrize("key", ["", "k" * 129, "密钥".encode(), "bad\x7fkey", "has space"])
def test_invalid_key_is_422(postgres_engine: Engine, key: str | bytes) -> None:
    organization_id, [(_, name)] = seed_org(postgres_engine)
    client = login(postgres_engine, name)
    title = f"plan-{uuid4()}"
    response = client.post(
        "/api/v1/review-plans", json={"title": title}, headers={"Idempotency-Key": key}
    )
    assert response.status_code == 422
    assert count_plans(postgres_engine, organization_id, title) == 0


def test_failed_creation_does_not_consume_the_key(postgres_engine: Engine) -> None:
    organization_id, [(_, name)] = seed_org(postgres_engine)
    client = login(postgres_engine, name)
    headers = _key()
    invalid = {**CASE_BODY, "title": f"case-{uuid4()}", "scenario_data": {}}

    rejected = client.post("/api/v1/review-cases", json=invalid, headers=headers)
    assert rejected.status_code == 422
    assert count_records(postgres_engine, organization_id) == 0

    valid = {**CASE_BODY, "title": invalid["title"]}
    created = client.post("/api/v1/review-cases", json=valid, headers=headers)
    assert created.status_code == 201
    assert REPLAYED not in created.headers


def test_key_cannot_read_another_organizations_resource(postgres_engine: Engine) -> None:
    _, [(_, name_a)] = seed_org(postgres_engine)
    org_b, [(_, name_b)] = seed_org(postgres_engine)
    client_a = login(postgres_engine, name_a)
    client_b = login(postgres_engine, name_b)
    headers = _key()
    plan_a = client_a.post("/api/v1/review-plans", json={"title": "A"}, headers=headers)

    plan_b = client_b.post("/api/v1/review-plans", json={"title": "B"}, headers=headers)

    assert plan_b.status_code == 201
    assert plan_b.json()["id"] != plan_a.json()["id"]
    assert plan_b.json()["organization_id"] == str(org_b)
    assert clone(client_b).get(f"/api/v1/review-plans/{plan_a.json()['id']}").status_code == 404


def test_failed_creation_with_a_key_can_be_retried_with_a_corrected_payload(
    postgres_engine: Engine,
) -> None:
    """A 422 rolls back the claim, so the same key is free for the corrected request."""

    organization_id, [(_, name)] = seed_org(postgres_engine)
    client = login(postgres_engine, name)
    headers = _key()
    title = f"case-{uuid4()}"

    rejected = client.post(
        "/api/v1/review-cases",
        json={**CASE_BODY, "title": title, "scenario_data": {"area_code": "area-a"}},
        headers=headers,
    )
    assert rejected.status_code == 422
    assert count_records(postgres_engine, organization_id) == 0

    corrected = client.post(
        "/api/v1/review-cases", json={**CASE_BODY, "title": title}, headers=headers
    )

    assert corrected.status_code == 201
    assert REPLAYED not in corrected.headers
    assert count_cases(postgres_engine, organization_id, title) == 1
    assert count_records(postgres_engine, organization_id) == 1
