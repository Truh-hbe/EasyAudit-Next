import pytest

from easyaudit_next.review_core.domain.models import FindingLifecycle, ReviewCaseLifecycle
from easyaudit_next.review_core.domain.scenario_capabilities import FindingOperationContext
from easyaudit_next.scenarios.process_review import PROCESS_REVIEW_V1


@pytest.mark.parametrize(
    "case_lifecycle",
    [
        ReviewCaseLifecycle.DRAFT,
        ReviewCaseLifecycle.SCHEDULED,
        ReviewCaseLifecycle.AWAITING_CLOSURE,
        ReviewCaseLifecycle.CLOSED,
        ReviewCaseLifecycle.CANCELLED,
    ],
)
def test_process_review_create_finding_requires_in_progress_case(
    case_lifecycle: ReviewCaseLifecycle,
) -> None:
    with pytest.raises(ValueError, match="only be created.*in_progress"):
        PROCESS_REVIEW_V1.finding_operations.validate_create(
            FindingOperationContext(case_lifecycle=case_lifecycle)
        )

    PROCESS_REVIEW_V1.finding_operations.validate_create(
        FindingOperationContext(case_lifecycle=ReviewCaseLifecycle.IN_PROGRESS)
    )


@pytest.mark.parametrize(
    "case_lifecycle",
    [
        ReviewCaseLifecycle.DRAFT,
        ReviewCaseLifecycle.SCHEDULED,
        ReviewCaseLifecycle.CANCELLED,
        ReviewCaseLifecycle.CLOSED,
    ],
)
def test_process_review_issue_rejects_inactive_case_lifecycles(
    case_lifecycle: ReviewCaseLifecycle,
) -> None:
    with pytest.raises(ValueError, match="cannot be issued or voided"):
        PROCESS_REVIEW_V1.finding_operations.validate_transition(
            "issue",
            FindingOperationContext(
                case_lifecycle=case_lifecycle,
                current_finding_lifecycle=FindingLifecycle.OPEN,
                participant_role_keys=frozenset(
                    {"owner", "responsible_department"}
                ),
            ),
        )


@pytest.mark.parametrize(
    "case_lifecycle",
    [ReviewCaseLifecycle.IN_PROGRESS, ReviewCaseLifecycle.AWAITING_CLOSURE],
)
def test_process_review_issue_requires_responsibility_and_allows_explicit_case_states(
    case_lifecycle: ReviewCaseLifecycle,
) -> None:
    base = FindingOperationContext(
        case_lifecycle=case_lifecycle,
        current_finding_lifecycle=FindingLifecycle.OPEN,
    )
    with pytest.raises(ValueError, match="responsible_department, owner"):
        PROCESS_REVIEW_V1.finding_operations.validate_transition("issue", base)

    owner_only = FindingOperationContext(
        case_lifecycle=case_lifecycle,
        current_finding_lifecycle=FindingLifecycle.OPEN,
        participant_role_keys=frozenset({"owner"}),
    )
    with pytest.raises(ValueError, match="responsible_department"):
        PROCESS_REVIEW_V1.finding_operations.validate_transition("issue", owner_only)

    PROCESS_REVIEW_V1.finding_operations.validate_transition(
        "issue",
        FindingOperationContext(
            case_lifecycle=case_lifecycle,
            current_finding_lifecycle=FindingLifecycle.OPEN,
            participant_role_keys=frozenset({"owner", "responsible_department"}),
        ),
    )


def test_process_review_terminal_finding_freezes_participant_management() -> None:
    for lifecycle in (FindingLifecycle.CLOSED, FindingLifecycle.VOIDED):
        with pytest.raises(ValueError, match="Terminal Finding participants"):
            PROCESS_REVIEW_V1.finding_operations.validate_participant_management(
                FindingOperationContext(
                    case_lifecycle=ReviewCaseLifecycle.AWAITING_CLOSURE,
                    current_finding_lifecycle=lifecycle,
                )
            )
