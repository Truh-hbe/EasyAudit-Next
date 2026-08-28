from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from easyaudit_next.platform.domain.models import User
from easyaudit_next.platform.persistence.models import UserRecord
from easyaudit_next.review_core.application.review_planning import ReviewPlanningService
from easyaudit_next.review_core.domain.ids import ReviewCaseId
from easyaudit_next.review_core.persistence.models import ActivityRecord


@dataclass(frozen=True, slots=True)
class CaseMemberView:
    case_id: UUID
    user_id: UUID
    role_key: str
    joined_at: datetime
    display_name: str


@dataclass(frozen=True, slots=True)
class ReviewCaseActivityView:
    id: UUID
    subject_id: UUID
    event_type: str
    actor_id: UUID | None
    occurred_at: datetime


class ReviewCaseContextQueryService:
    """Presentation reads that only execute after ordinary ReviewCase authorization."""

    def __init__(
        self,
        session: Session,
        planning: ReviewPlanningService,
    ) -> None:
        self._session = session
        self._planning = planning

    def list_member_views(
        self,
        actor: User,
        case_id: ReviewCaseId,
    ) -> tuple[CaseMemberView, ...]:
        # ReviewPlanningService owns the canonical current VIEW_CASE decision and
        # returns the authoritative CaseMember relationships only after it succeeds.
        members = self._planning.list_case_members(actor, case_id)
        user_ids = {member.user_id for member in members}
        users = tuple(
            self._session.scalars(
                select(UserRecord).where(
                    UserRecord.organization_id == actor.organization_id,
                    UserRecord.id.in_(user_ids),
                )
            )
        )
        display_name_by_id = {user.id: user.display_name for user in users}
        views: list[CaseMemberView] = []
        for member in members:
            display_name = display_name_by_id.get(member.user_id)
            if display_name is None:
                raise LookupError("CaseMember display User not found")
            views.append(
                CaseMemberView(
                    case_id=member.case_id,
                    user_id=member.user_id,
                    role_key=member.role_key,
                    joined_at=member.joined_at,
                    display_name=display_name,
                )
            )
        return tuple(views)

    def list_case_activities(
        self,
        actor: User,
        case_id: ReviewCaseId,
    ) -> tuple[ReviewCaseActivityView, ...]:
        review_case = self._planning.get_case(actor, case_id)
        records = tuple(
            self._session.scalars(
                select(ActivityRecord)
                .where(
                    ActivityRecord.organization_id == actor.organization_id,
                    ActivityRecord.review_case_id == review_case.id,
                    ActivityRecord.finding_id.is_(None),
                    ActivityRecord.action_item_id.is_(None),
                    ActivityRecord.submission_id.is_(None),
                )
                .order_by(ActivityRecord.occurred_at.desc(), ActivityRecord.id.desc())
            )
        )
        return tuple(
            ReviewCaseActivityView(
                id=record.id,
                subject_id=review_case.id,
                event_type=record.event_type,
                actor_id=record.actor_id,
                occurred_at=record.occurred_at,
            )
            for record in records
        )
