from datetime import datetime

from sqlalchemy import update as sa_update

from easyaudit_next.platform.domain.ids import AuthSessionId
from easyaudit_next.platform.domain.models import AuthSession
from easyaudit_next.platform.persistence.models import AuthSessionRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyAuthSessionRepository
from easyaudit_next.platform.session_touch import SESSION_TOUCH_INTERVAL


class ThrottledSqlAlchemyAuthSessionRepository(SqlAlchemyAuthSessionRepository):
    """AuthSession adapter whose touch path is a stale-only PostgreSQL CAS."""

    def touch_if_active(
        self,
        session_id: AuthSessionId,
        expected_token_hash: str,
        touched_at: datetime,
    ) -> AuthSession | None:
        record = self._session.scalar(
            sa_update(AuthSessionRecord)
            .where(
                AuthSessionRecord.id == session_id,
                AuthSessionRecord.token_hash == expected_token_hash,
                AuthSessionRecord.revoked_at.is_(None),
                AuthSessionRecord.expires_at > touched_at,
                AuthSessionRecord.last_seen_at < touched_at - SESSION_TOUCH_INTERVAL,
            )
            .values(last_seen_at=touched_at)
            .returning(AuthSessionRecord),
            execution_options={"synchronize_session": False},
        )
        return self._to_domain(record) if record is not None else None
