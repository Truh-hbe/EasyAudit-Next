import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from easyaudit_next.review_core.persistence.models import EvidenceRecord
from tests.conftest import FakeS3
from tests.integration.test_review_resource_queries import SeededCollaboration


def new_key(seeded: SeededCollaboration) -> str:
    return f"org/{seeded.organization_id}/evidence/{uuid4()}"


def put(fake: FakeS3, key: str, content: bytes) -> None:
    fake.client().put_object(Bucket=fake.bucket, Key=key, Body=content)


def register_row(
    engine: Engine, seeded: SeededCollaboration, key: str, content: bytes
) -> EvidenceRecord:
    """Metadata as the upload route would have written it for `content`."""
    record = EvidenceRecord(
        id=uuid4(),
        organization_id=seeded.organization_id,
        action_item_id=seeded.action_id,
        storage_key=key,
        original_name="record.pdf",
        content_type="application/pdf",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        description=None,
        uploaded_by=seeded.owner_id,
        created_at=datetime.now(UTC),
    )
    with Session(engine, expire_on_commit=False) as session, session.begin():
        session.add(record)
    return record
