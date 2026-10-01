from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.review_core.application.create_idempotency import (
    CreateOperation,
    StoredCreate,
)
from easyaudit_next.review_core.persistence.models import CreateIdempotencyRecord


class SqlAlchemyCreateIdempotencyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def claim(
        self,
        organization_id: OrganizationId,
        actor_user_id: UserId,
        operation: CreateOperation,
        key: str,
        fingerprint: str,
        resource_id: UUID,
    ) -> bool:
        is_plan = operation is CreateOperation.CREATE_REVIEW_PLAN
        claimed = self._session.execute(
            insert(CreateIdempotencyRecord)
            .values(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                operation=operation.value,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                review_plan_id=resource_id if is_plan else None,
                review_case_id=None if is_plan else resource_id,
                response_status=201,
            )
            .on_conflict_do_nothing()
            .returning(CreateIdempotencyRecord.idempotency_key)
        ).scalar_one_or_none()
        return claimed is not None

    def find(
        self,
        organization_id: OrganizationId,
        actor_user_id: UserId,
        operation: CreateOperation,
        key: str,
    ) -> StoredCreate | None:
        # A new statement: under READ COMMITTED it sees the row committed by the claim's winner.
        row = self._session.execute(
            select(
                CreateIdempotencyRecord.request_fingerprint,
                CreateIdempotencyRecord.review_plan_id,
                CreateIdempotencyRecord.review_case_id,
            ).where(
                CreateIdempotencyRecord.organization_id == organization_id,
                CreateIdempotencyRecord.actor_user_id == actor_user_id,
                CreateIdempotencyRecord.operation == operation.value,
                CreateIdempotencyRecord.idempotency_key == key,
            )
        ).one_or_none()
        if row is None:
            return None
        resource_id = row.review_plan_id or row.review_case_id
        assert resource_id is not None  # ck_create_idempotency_resource
        return StoredCreate(row.request_fingerprint, resource_id)
