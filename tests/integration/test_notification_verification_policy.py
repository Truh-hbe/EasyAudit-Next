import os
from collections.abc import Iterator
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from easyaudit_next.collaboration.notification_orchestration import NotificationOrchestrator
from easyaudit_next.composition import build_notification_service
from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.persistence.models import OrganizationRecord, UserRecord
from easyaudit_next.review_core.application.mutation_results import RectificationSubmissionResult
from easyaudit_next.review_core.domain.ids import (
    ActivityId,
    FindingId,
    ReviewCaseId,
    SubmissionId,
)
from easyaudit_next.review_core.domain.models import (
    Finding,
    FindingLifecycle,
    FindingSeverity,
    Scenario,
    ScenarioKey,
    ScenarioVersion,
    Submission,
    SubmissionPurpose,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActorKind,
    AuthorizationContext,
    PermissionSource,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
from easyaudit_next.review_core.persistence.models import (
    ActivityRecord,
    FindingParticipantRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
    SubmissionRecord,
)
from easyaudit_next.scenarios.process_review import PROCESS_REVIEW_V1
from tests.integration.notification_test_support import (
    NOW,
    notification_recipients_for_origin,
)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


class _TargetOwnerVerifies:
    def allows(self, permission: str, context: AuthorizationContext) -> bool:
        if permission != "verify_finding":
            return False
        return any(
            grant.role_key == "owner"
            and grant.actor_kind is ActorKind.USER
            and grant.source is PermissionSource.DIRECT
            for grant in context.finding_role_grants
        )


def test_exact_historical_scenario_policy_beats_reviewer_shortcut_and_sibling_grants(
    postgres_engine: Engine,
) -> None:
    organization_id = OrganizationId(uuid4())
    submitter_id = UserId(uuid4())
    target_owner_id = UserId(uuid4())
    sibling_owner_id = UserId(uuid4())
    system_admin_id = UserId(uuid4())
    scenario_id = uuid4()
    scenario_version_id = uuid4()
    case_id = ReviewCaseId(uuid4())
    target_finding_id = FindingId(uuid4())
    sibling_finding_id = FindingId(uuid4())
    submission_id = SubmissionId(uuid4())
    activity_id = ActivityId(uuid4())
    scenario_key = ScenarioKey("target_owner_verifies")
    scenario_version = ScenarioVersion(7)

    custom_policy = replace(
        PROCESS_REVIEW_V1,
        scenario=Scenario(
            key=scenario_key,
            version=scenario_version,
            name="Target owner verifies",
        ),
        authorization=_TargetOwnerVerifies(),
    )
    registry = ScenarioRegistry()
    registry.register(custom_policy)

    with Session(postgres_engine) as session, session.begin():
        session.add(
            OrganizationRecord(
                id=organization_id,
                name=f"Scenario notification {organization_id}",
            )
        )
        session.flush()
        session.add_all(
            [
                UserRecord(
                    id=submitter_id,
                    organization_id=organization_id,
                    display_name="Submitter",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=target_owner_id,
                    organization_id=organization_id,
                    display_name="Target Owner",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=sibling_owner_id,
                    organization_id=organization_id,
                    display_name="Sibling Owner",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=system_admin_id,
                    organization_id=organization_id,
                    display_name="System Admin",
                    platform_role="system_admin",
                ),
            ]
        )
        session.flush()
        session.add(
            ScenarioRecord(
                id=scenario_id,
                organization_id=organization_id,
                key=scenario_key,
                name="Target owner verifies",
            )
        )
        session.flush()
        session.add(
            ScenarioVersionRecord(
                id=scenario_version_id,
                scenario_id=scenario_id,
                organization_id=organization_id,
                version=scenario_version,
                published_at=NOW,
            )
        )
        session.flush()
        session.add(
            ReviewCaseRecord(
                id=case_id,
                organization_id=organization_id,
                scenario_version_id=scenario_version_id,
                title="Target-specific verification",
                lifecycle="in_progress",
                scenario_data_json={},
                created_by=submitter_id,
                created_at=NOW,
            )
        )
        session.flush()
        session.add_all(
            [
                FindingRecord(
                    id=target_finding_id,
                    organization_id=organization_id,
                    case_id=case_id,
                    title="Target finding",
                    severity="high",
                    lifecycle="verifying",
                    raised_by=submitter_id,
                    raised_at=NOW,
                    scenario_data_json={},
                ),
                FindingRecord(
                    id=sibling_finding_id,
                    organization_id=organization_id,
                    case_id=case_id,
                    title="Sibling finding",
                    severity="medium",
                    lifecycle="open",
                    raised_by=submitter_id,
                    raised_at=NOW,
                    scenario_data_json={},
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                FindingParticipantRecord(
                    id=uuid4(),
                    organization_id=organization_id,
                    finding_id=target_finding_id,
                    user_id=target_owner_id,
                    role_key="owner",
                    assigned_at=NOW,
                ),
                FindingParticipantRecord(
                    id=uuid4(),
                    organization_id=organization_id,
                    finding_id=sibling_finding_id,
                    user_id=sibling_owner_id,
                    role_key="owner",
                    assigned_at=NOW,
                ),
            ]
        )
        session.flush()
        session.add(
            SubmissionRecord(
                id=submission_id,
                organization_id=organization_id,
                case_id=case_id,
                finding_id=target_finding_id,
                purpose="rectification",
                submitted_by=submitter_id,
                submitted_at=NOW,
                payload_json={"stage": "completion", "comment": "ready"},
            )
        )
        session.flush()
        session.add(
            ActivityRecord(
                id=activity_id,
                organization_id=organization_id,
                actor_id=submitter_id,
                event_type="finding.submitted_for_verification",
                occurred_at=NOW,
                submission_id=submission_id,
                metadata_json={"finding_id": str(target_finding_id)},
            )
        )
        session.flush()

        finding = Finding(
            id=target_finding_id,
            organization_id=organization_id,
            case_id=case_id,
            title="Target finding",
            description=None,
            severity=FindingSeverity.HIGH,
            lifecycle=FindingLifecycle.VERIFYING,
            raised_by=submitter_id,
            raised_at=NOW,
            scenario_data={},
        )
        submission = Submission(
            id=submission_id,
            organization_id=organization_id,
            case_id=case_id,
            finding_id=target_finding_id,
            purpose=SubmissionPurpose.RECTIFICATION,
            submitted_by=submitter_id,
            submitted_at=NOW,
            payload={"stage": "completion", "comment": "ready"},
        )
        NotificationOrchestrator(
            session,
            registry,
            build_notification_service(session),
        ).rectification_submitted(
            RectificationSubmissionResult(
                submission=submission,
                finding=finding,
                activity_id=activity_id,
            )
        )

    with Session(postgres_engine) as verification:
        recipients = notification_recipients_for_origin(
            verification,
            organization_id,
            activity_id,
            NotificationKind.FINDING_SUBMITTED_FOR_VERIFICATION,
        )
        assert recipients == {target_owner_id}
        assert sibling_owner_id not in recipients
        assert system_admin_id not in recipients
        assert submitter_id not in recipients
