import argparse
import getpass
import json
import sys
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pwdlib import PasswordHash
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from easyaudit_next.collaboration.reminder_sweep import describe_failure
from easyaudit_next.collaboration.scheduler_runs import (
    JOB_AUTOMATIC_REMINDER_SWEEP,
    SchedulerRunRecord,
    finish_run,
    latest_run,
    start_run,
)
from easyaudit_next.composition import (
    build_per_candidate_reminder_sweep,
    build_scenario_registry,
)
from easyaudit_next.infrastructure.database import (
    create_database_engine,
    create_session_factory,
    session_scope,
)
from easyaudit_next.platform.application.authentication import normalize_login_name
from easyaudit_next.platform.application.login_throttle import (
    LoginThrottlePolicy,
    LoginThrottleService,
)
from easyaudit_next.platform.application.password_policy import (
    PasswordPolicyError,
    validate_local_password,
)
from easyaudit_next.platform.application.services import IdentityOrganizationService
from easyaudit_next.platform.domain.ids import OrganizationId, PlatformAuditEventId
from easyaudit_next.platform.domain.models import (
    LocalCredential,
    PlatformAuditEvent,
    PlatformRole,
)
from easyaudit_next.platform.persistence.models import AuthSessionRecord
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyDepartmentRepository,
    SqlAlchemyLocalCredentialRepository,
    SqlAlchemyLoginThrottleRepository,
    SqlAlchemyOrganizationRepository,
    SqlAlchemyPlatformAuditRepository,
    SqlAlchemyUserRepository,
)
from easyaudit_next.platform.settings import get_settings
from easyaudit_next.review_core.application.scenario_catalog import ScenarioCatalogService
from easyaudit_next.review_core.domain.models import ScenarioKey, ScenarioVersion
from easyaudit_next.review_core.persistence.repositories import SqlAlchemyScenarioCatalogRepository


def _ensure_bootstrap_available(session: Session) -> None:
    if SqlAlchemyOrganizationRepository(session).list_all():
        raise RuntimeError("Bootstrap refused: an Organization already exists")


def bootstrap_admin_in_session(
    session: Session,
    organization_name: str,
    admin_name: str,
    login_name: str,
    password: str,
    *,
    now: datetime | None = None,
) -> None:
    _ensure_bootstrap_available(session)
    validate_local_password(password)
    organizations = SqlAlchemyOrganizationRepository(session)
    departments = SqlAlchemyDepartmentRepository(session)
    users = SqlAlchemyUserRepository(session)
    identity = IdentityOrganizationService(organizations, departments, users)
    organization = identity.create_organization(organization_name)
    admin = identity.create_user(
        organization.id,
        admin_name,
        platform_role=PlatformRole.SYSTEM_ADMIN,
    )
    occurred_at = now or datetime.now(UTC)
    SqlAlchemyLocalCredentialRepository(session).add(
        LocalCredential(
            user_id=admin.id,
            organization_id=organization.id,
            login_name=login_name.strip().lower(),
            password_hash=PasswordHash.recommended().hash(password),
            password_changed_at=occurred_at,
        )
    )
    SqlAlchemyPlatformAuditRepository(session).add(
        PlatformAuditEvent(
            id=PlatformAuditEventId(uuid4()),
            organization_id=organization.id,
            actor_user_id=admin.id,
            target_user_id=admin.id,
            event_type="bootstrap.system_admin_created",
            occurred_at=occurred_at,
        )
    )


def bootstrap_admin(organization_name: str, admin_name: str, login_name: str) -> None:
    engine = create_database_engine()
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            _ensure_bootstrap_available(session)
            password = getpass.getpass("Initial admin password: ")
            confirmation = getpass.getpass("Confirm password: ")
            if password != confirmation:
                raise PasswordPolicyError("Password confirmation does not match")
            bootstrap_admin_in_session(
                session,
                organization_name,
                admin_name,
                login_name,
                password,
            )
    finally:
        engine.dispose()


def publish_scenario_in_session(
    session: Session,
    organization_id: OrganizationId,
    scenario_key: ScenarioKey,
    scenario_version: ScenarioVersion,
) -> None:
    """Publish one exact, code-defined Scenario version for an existing Organization."""

    if SqlAlchemyOrganizationRepository(session).get(organization_id) is None:
        raise LookupError(f"Organization {organization_id} does not exist")
    ScenarioCatalogService(
        SqlAlchemyScenarioCatalogRepository(session),
        build_scenario_registry(),
    ).publish(organization_id, scenario_key, scenario_version)


def publish_scenario(
    organization_id: OrganizationId,
    scenario_key: ScenarioKey,
    scenario_version: ScenarioVersion,
) -> None:
    engine = create_database_engine()
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            publish_scenario_in_session(
                session,
                organization_id,
                scenario_key,
                scenario_version,
            )
    finally:
        engine.dispose()


def cleanup_auth_in_session(
    session: Session,
    *,
    window: timedelta,
    now: datetime | None = None,
    clear_login_name: str | None = None,
) -> dict[str, int]:
    """Delete expired login_throttle windows. Never touches auth_sessions: they are audit
    anchors (FK RESTRICT) and `expires_at` already makes an expired one unusable. The count of
    expired sessions is reported for scale only."""
    current = now or datetime.now(UTC)
    throttle = LoginThrottleService(
        lambda: nullcontext(SqlAlchemyLoginThrottleRepository(session)),
        LoginThrottlePolicy(window=window),
    )
    deleted = throttle.purge_expired(now=current)
    counts: dict[str, int] = {}
    if clear_login_name is not None:
        counts["login_name_cleared"] = throttle.clear_login_name(
            normalize_login_name(clear_login_name)
        )
    expired_sessions = session.scalar(
        select(func.count()).select_from(AuthSessionRecord).where(
            AuthSessionRecord.expires_at <= current
        )
    )
    return {
        "login_throttle_deleted": deleted,
        **counts,
        "expired_sessions": int(expired_sessions or 0),
    }


def cleanup_auth(clear_login_name: str | None = None) -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            counts = cleanup_auth_in_session(
                session,
                window=timedelta(seconds=settings.login_throttle_window_seconds),
                clear_login_name=clear_login_name,
            )
    finally:
        engine.dispose()
    print(json.dumps({"event": "cleanup_auth", **counts}))


_MAX_OCCURRENCE_KEY_CHARS = 200
_MAX_ERROR_SUMMARY_CHARS = 500


def default_occurrence_key(as_of: datetime, timezone: str) -> str:
    """`daily:<local date of as_of>`: every run on the same local day shares one key."""
    return f"daily:{as_of.astimezone(ZoneInfo(timezone)).date().isoformat()}"


def run_reminder_sweep_job(
    factory: sessionmaker[Session],
    *,
    as_of: datetime,
    occurrence_key: str,
    organization_id: OrganizationId | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Run the sweep and leave a `scheduler_runs` row. Three separate transactions:

    (a) insert the `running` row and commit; (b) the sweep, one short transaction per candidate
    (see `AutomaticReminderSweep.per_candidate`); (c) update the row to its final state. The row
    never decides whether the sweep runs: Notification's unique index does the deduplication,
    so a rerun always executes in full. A crash between (a) and (c) leaves the row `running`.
    """
    with session_scope(factory) as session:
        run_id = start_run(
            session,
            job_key=JOB_AUTOMATIC_REMINDER_SWEEP,
            occurrence_key=occurrence_key,
            as_of=as_of,
            started_at=now(),
        )

    scanned = created = deduped = failed = 0
    error_summary: str | None = None
    try:
        result = build_per_candidate_reminder_sweep(factory).run_once(
            occurrence_key=occurrence_key, as_of=as_of, organization_id=organization_id
        )
    except Exception as exc:  # the whole sweep could not run (e.g. discovery failed)
        error_summary = f"sweep_aborted: {describe_failure(exc)}"
        status = "failed"
    else:
        scanned = result.case_candidates + result.action_candidates
        created = result.created_deliveries
        deduped = result.deduped_deliveries
        failed = result.failed_candidates
        status = "failed" if failed else "succeeded"
        if failed:
            kinds = ", ".join(f"{label} x{count}" for label, count in result.failure_types)
            error_summary = f"failed_candidates={failed}: {kinds}"
    if error_summary is not None:
        error_summary = error_summary[:_MAX_ERROR_SUMMARY_CHARS]

    finished_at = now()
    with session_scope(factory) as session:
        finish_run(
            session,
            run_id,
            status=status,
            finished_at=finished_at,
            scanned_count=scanned,
            created_count=created,
            deduped_count=deduped,
            failed_count=failed,
            error_summary=error_summary,
        )
    return {
        "event": "run_reminder_sweep",
        "run_id": str(run_id),
        "job_key": JOB_AUTOMATIC_REMINDER_SWEEP,
        "occurrence_key": occurrence_key,
        "as_of": as_of.isoformat(),
        "status": status,
        "scanned_count": scanned,
        "created_count": created,
        "deduped_count": deduped,
        "failed_count": failed,
        "error_summary": error_summary,
    }


def run_reminder_sweep(as_of: datetime | None, occurrence_key: str | None) -> int:
    settings = get_settings()
    resolved_as_of = (as_of or datetime.now(UTC)).astimezone(UTC)
    key = occurrence_key or default_occurrence_key(resolved_as_of, settings.reminder_timezone)
    engine = create_database_engine(settings)
    try:
        outcome = run_reminder_sweep_job(
            create_session_factory(engine), as_of=resolved_as_of, occurrence_key=key
        )
    finally:
        engine.dispose()
    print(json.dumps(outcome))
    return 0 if outcome["status"] == "succeeded" else 1


def _run_summary(run: SchedulerRunRecord) -> dict[str, Any]:
    return {
        "run_id": str(run.id),
        "occurrence_key": run.occurrence_key,
        "as_of": run.as_of.isoformat(),
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "scanned_count": run.scanned_count,
        "created_count": run.created_count,
        "deduped_count": run.deduped_count,
        "failed_count": run.failed_count,
        "error_summary": run.error_summary,
    }


def scheduler_status_in_session(
    session: Session,
    *,
    job_key: str,
    max_age_hours: float,
    now: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """Latest run as JSON, plus whether the job is healthy.

    Unhealthy: no run at all, the latest run failed, or the newest `succeeded` run finished
    longer than `max_age_hours` ago. A latest run that is still `running` (or crashed while
    running) is not a failure by itself; freshness is judged on the last success.
    """
    current = now or datetime.now(UTC)
    latest = latest_run(session, job_key)
    succeeded = latest_run(session, job_key, status="succeeded")
    reasons: list[str] = []
    if latest is None:
        reasons.append("never_run")
    elif latest.status == "failed":
        reasons.append("latest_run_failed")
    if latest is not None and (
        succeeded is None
        or succeeded.finished_at is None
        or succeeded.finished_at < current - timedelta(hours=max_age_hours)
    ):
        reasons.append("last_success_stale")
    payload = {
        "event": "scheduler_status",
        "job_key": job_key,
        "healthy": not reasons,
        "reasons": reasons,
        "max_age_hours": max_age_hours,
        "latest": _run_summary(latest) if latest else None,
        "last_succeeded": _run_summary(succeeded) if succeeded else None,
    }
    return payload, not reasons


def scheduler_status(job_key: str, max_age_hours: float) -> int:
    engine = create_database_engine()
    try:
        with create_session_factory(engine)() as session:
            payload, healthy = scheduler_status_in_session(
                session, job_key=job_key, max_age_hours=max_age_hours
            )
    finally:
        engine.dispose()
    print(json.dumps(payload))
    return 0 if healthy else 1


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be ISO 8601") from exc
    if parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("must include a UTC offset (e.g. 2026-10-02T01:00:00Z)")
    return parsed


def _occurrence_key(value: str) -> str:
    if (
        not value
        or value != value.strip()
        or len(value) > _MAX_OCCURRENCE_KEY_CHARS
    ):
        raise argparse.ArgumentTypeError(
            f"must be non-blank, unpadded, at most {_MAX_OCCURRENCE_KEY_CHARS} characters"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="easyaudit-next")
    subparsers = parser.add_subparsers(dest="command", required=True)
    bootstrap = subparsers.add_parser(
        "bootstrap-admin",
        help="Create the first Organization and system administrator without default credentials",
    )
    bootstrap.add_argument("--organization-name", required=True)
    bootstrap.add_argument("--admin-name", required=True)
    bootstrap.add_argument("--login-name", required=True)
    publish = subparsers.add_parser(
        "publish-scenario",
        help="Publish one exact code-defined Scenario version for an Organization",
    )
    publish.add_argument("--organization-id", required=True, type=UUID)
    publish.add_argument("--key", required=True, type=ScenarioKey)
    publish.add_argument("--version", required=True, type=int)
    subparsers.add_parser(
        "cleanup-auth",
        help="Delete expired login_throttle windows (sessions are kept; only counted)",
    ).add_argument(
        "--clear-login-name",
        help="Also drop every login throttle counter of this login name (unblocks it)",
    )
    sweep = subparsers.add_parser(
        "run-reminder-sweep",
        help="Run the automatic reminder sweep once and record the run (exit 1 if any failed)",
    )
    sweep.add_argument("--as-of", type=_aware_datetime, help="ISO 8601 with offset; default: now")
    sweep.add_argument(
        "--occurrence-key",
        type=_occurrence_key,
        help="default: daily:<date of as-of in REMINDER_TIMEZONE>",
    )
    status = subparsers.add_parser(
        "scheduler-status",
        help="Print the latest run of a scheduled job; exit 1 if failed, stale or never run",
    )
    status.add_argument("--job", default=JOB_AUTOMATIC_REMINDER_SWEEP)
    status.add_argument("--max-age-hours", type=float, default=26.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "bootstrap-admin":
        bootstrap_admin(args.organization_name, args.admin_name, args.login_name)
    elif args.command == "publish-scenario":
        publish_scenario(
            OrganizationId(args.organization_id),
            ScenarioKey(args.key),
            ScenarioVersion(args.version),
        )
    elif args.command == "cleanup-auth":
        cleanup_auth(args.clear_login_name)
    elif args.command == "run-reminder-sweep":
        sys.exit(run_reminder_sweep(args.as_of, args.occurrence_key))
    elif args.command == "scheduler-status":
        sys.exit(scheduler_status(args.job, args.max_age_hours))


if __name__ == "__main__":
    main()
