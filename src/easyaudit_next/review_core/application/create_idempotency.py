import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.domain.models import User


class CreateOperation(StrEnum):
    CREATE_REVIEW_PLAN = "create_review_plan"
    CREATE_REVIEW_CASE = "create_review_case"


class IdempotencyKeyReuseError(RuntimeError):
    """The Idempotency-Key was already used for a different request."""


@dataclass(frozen=True, slots=True)
class StoredCreate:
    request_fingerprint: str
    resource_id: UUID


class CreateIdempotencyRepository(Protocol):
    def claim(
        self,
        organization_id: OrganizationId,
        actor_user_id: UserId,
        operation: CreateOperation,
        key: str,
        fingerprint: str,
        resource_id: UUID,
    ) -> bool:
        """INSERT ... ON CONFLICT DO NOTHING RETURNING; True only for the inserting caller."""
        ...

    def find(
        self,
        organization_id: OrganizationId,
        actor_user_id: UserId,
        operation: CreateOperation,
        key: str,
    ) -> StoredCreate | None: ...


def _canonical(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def request_fingerprint(payload: Mapping[str, object]) -> str:
    """sha256 over the validated payload: sorted keys, datetimes as UTC, no whitespace."""

    canonical = json.dumps(
        _canonical(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return sha256(canonical.encode("ascii")).hexdigest()


class CreateIdempotencyService:
    """Claim an Idempotency-Key for ReviewPlan / ReviewCase creation.

    The unique index is the arbiter: the claim is the first statement of the creation
    transaction and a concurrent claimant of the same key waits for it to commit or roll back.
    There is deliberately no "SELECT, then INSERT".
    """

    def __init__(self, repository: CreateIdempotencyRepository) -> None:
        self._repository = repository

    def claim(
        self,
        actor: User,
        operation: CreateOperation,
        key: str,
        payload: Mapping[str, object],
        new_resource_id: UUID,
    ) -> UUID | None:
        """Return None when this transaction owns the key, else the first request's resource id."""

        fingerprint = request_fingerprint(payload)
        if self._repository.claim(
            actor.organization_id, actor.id, operation, key, fingerprint, new_resource_id
        ):
            return None
        stored = self._repository.find(actor.organization_id, actor.id, operation, key)
        if stored is None:
            raise RuntimeError("Idempotency record vanished after a conflicting claim")
        if stored.request_fingerprint != fingerprint:
            raise IdempotencyKeyReuseError("Idempotency-Key reused with a different request")
        return stored.resource_id
