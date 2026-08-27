from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.review_core.domain.ids import ActivityId
from easyaudit_next.review_core.persistence.models import ScenarioRecord, ScenarioVersionRecord

NOW = datetime(2026, 8, 27, 15, 30, tzinfo=UTC)


def seed_process_review_users(
    engine: Engine,
) -> tuple[OrganizationId, DepartmentId, dict[str, UserId]]:
    organization_id = OrganizationId(uuid4())
    department_id = DepartmentId(uuid4())
    users = {
        "lead": UserId(uuid4()),
        "owner": UserId(uuid4()),
        "reviewer": UserId(uuid4()),
        "system_admin": UserId(uuid4()),
        "action_assignee": UserId(uuid4()),
        "department_member": UserId(uuid4()),
        "inactive_department_member": UserId(uuid4()),
        "late_department_member": UserId(uuid4()),
        "observer_a": UserId(uuid4()),
        "observer_b": UserId(uuid4()),
        "unrelated": UserId(uuid4()),
    }
    scenario_id = uuid4()

    with Session(engine) as session, session.begin():
        session.add(
            OrganizationRecord(
                id=organization_id,
                name=f"Notification orchestration {organization_id}",
            )
        )
        session.flush()
        session.add(
            DepartmentRecord(
                id=department_id,
                organization_id=organization_id,
                name="Responsible Department",
            )
        )
        session.flush()
        for name, user_id in users.items():
            session.add(
                UserRecord(
                    id=user_id,
                    organization_id=organization_id,
                    primary_department_id=(
                        department_id
                        if name in {"department_member", "inactive_department_member"}
                        else None
                    ),
                    display_name=name.replace("_", " ").title(),
                    platform_role=(
                        "system_admin" if name == "system_admin" else "ordinary_user"
                    ),
                    is_active=name != "inactive_department_member",
                )
            )
        session.flush()
        session.add(
            ScenarioRecord(
                id=scenario_id,
                organization_id=organization_id,
                key="process_review",
                name="Process Review",
            )
        )
        session.flush()
        session.add(
            ScenarioVersionRecord(
                id=uuid4(),
                scenario_id=scenario_id,
                organization_id=organization_id,
                version=1,
                published_at=NOW,
            )
        )
    return organization_id, department_id, users


def notification_recipients_for_origin(
    session: Session,
    organization_id: OrganizationId,
    origin_activity_id: ActivityId,
    kind: NotificationKind,
) -> set[UUID]:
    return set(
        session.scalars(
            select(NotificationRecord.recipient_user_id).where(
                NotificationRecord.organization_id == organization_id,
                NotificationRecord.origin_activity_id == origin_activity_id,
                NotificationRecord.kind == kind.value,
            )
        )
    )
