from pathlib import Path
from unittest import TestCase

from easyaudit_next.review_core.domain.models import (
    ActionItemLifecycle,
    AssignmentRole,
    FindingLifecycle,
    ReviewCaseLifecycle,
    ScenarioKey,
    ScenarioVersion,
    SubmissionPurpose,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActionItemTransitionContext,
    AuthorizationContext,
    FindingTransitionContext,
    ReviewCaseTransitionContext,
    WorkflowTransitionError,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
from easyaudit_next.scenarios.process_review import (
    PROCESS_REVIEW_V1,
    ProcessReviewPermission,
    register_process_review_v1,
)


class ProcessReviewV1Test(TestCase):
    def test_registration_exposes_exact_versioned_capabilities(self) -> None:
        registry = ScenarioRegistry()

        registered = register_process_review_v1(registry)

        self.assertIs(registered, PROCESS_REVIEW_V1)
        self.assertIs(
            registry.get(ScenarioKey("process_review"), ScenarioVersion(1)),
            PROCESS_REVIEW_V1,
        )
        self.assertEqual(
            ("lead", "auditor", "reviewer", "observer"),
            PROCESS_REVIEW_V1.case_role_keys,
        )
        self.assertEqual(
            ("responsible_department", "owner", "collaborator"),
            PROCESS_REVIEW_V1.finding_participant_role_keys,
        )

    def test_case_workflow_distinguishes_fieldwork_from_closure(self) -> None:
        workflow = PROCESS_REVIEW_V1.case_workflow
        empty = ReviewCaseTransitionContext()

        scheduled = workflow.transition(ReviewCaseLifecycle.DRAFT, "schedule", empty)
        started = workflow.transition(scheduled, "start", empty)
        awaiting = workflow.transition(started, "finish_fieldwork", empty)

        self.assertIs(awaiting, ReviewCaseLifecycle.AWAITING_CLOSURE)
        with self.assertRaisesRegex(WorkflowTransitionError, "every Finding"):
            workflow.transition(awaiting, "close", empty)

        closed = workflow.transition(
            awaiting,
            "close",
            ReviewCaseTransitionContext(all_findings_terminal=True),
        )
        self.assertIs(closed, ReviewCaseLifecycle.CLOSED)

    def test_case_cancel_requires_reason_and_is_limited_to_pre_start_states(self) -> None:
        workflow = PROCESS_REVIEW_V1.case_workflow

        with self.assertRaisesRegex(WorkflowTransitionError, "requires a reason"):
            workflow.transition(ReviewCaseLifecycle.DRAFT, "cancel", ReviewCaseTransitionContext())

        cancelled = workflow.transition(
            ReviewCaseLifecycle.SCHEDULED,
            "cancel",
            ReviewCaseTransitionContext(reason="计划取消"),
        )
        self.assertIs(cancelled, ReviewCaseLifecycle.CANCELLED)

        with self.assertRaises(WorkflowTransitionError):
            workflow.transition(
                ReviewCaseLifecycle.IN_PROGRESS,
                "cancel",
                ReviewCaseTransitionContext(reason="too late"),
            )

    def test_finding_workflow_requires_completed_actions_before_verification(self) -> None:
        workflow = PROCESS_REVIEW_V1.finding_workflow
        rectifying = workflow.transition(
            FindingLifecycle.OPEN,
            "issue",
            FindingTransitionContext(),
        )
        self.assertIs(rectifying, FindingLifecycle.RECTIFYING)

        with self.assertRaisesRegex(WorkflowTransitionError, "at least one"):
            workflow.transition(
                rectifying,
                "submit_for_verification",
                FindingTransitionContext(),
            )
        with self.assertRaisesRegex(WorkflowTransitionError, "must be done"):
            workflow.transition(
                rectifying,
                "submit_for_verification",
                FindingTransitionContext(
                    non_cancelled_action_count=2,
                    all_non_cancelled_actions_done=False,
                ),
            )

        verifying = workflow.transition(
            rectifying,
            "submit_for_verification",
            FindingTransitionContext(
                non_cancelled_action_count=2,
                all_non_cancelled_actions_done=True,
            ),
        )
        self.assertIs(verifying, FindingLifecycle.VERIFYING)
        self.assertIs(
            workflow.transition(verifying, "approve", FindingTransitionContext()),
            FindingLifecycle.CLOSED,
        )

    def test_finding_void_reject_and_reopen_require_reason(self) -> None:
        workflow = PROCESS_REVIEW_V1.finding_workflow

        for lifecycle, action in (
            (FindingLifecycle.OPEN, "void"),
            (FindingLifecycle.VERIFYING, "reject"),
            (FindingLifecycle.CLOSED, "reopen"),
        ):
            with self.subTest(action=action):
                with self.assertRaisesRegex(WorkflowTransitionError, "requires a reason"):
                    workflow.transition(lifecycle, action, FindingTransitionContext())

        self.assertIs(
            workflow.transition(
                FindingLifecycle.VERIFYING,
                "reject",
                FindingTransitionContext(reason="整改证据不足"),
            ),
            FindingLifecycle.RECTIFYING,
        )
        self.assertIs(
            workflow.transition(
                FindingLifecycle.CLOSED,
                "reopen",
                FindingTransitionContext(reason="现场复发"),
            ),
            FindingLifecycle.RECTIFYING,
        )

    def test_action_workflow_stays_small_and_supports_rework(self) -> None:
        workflow = PROCESS_REVIEW_V1.action_workflow
        empty = ActionItemTransitionContext()

        in_progress = workflow.transition(ActionItemLifecycle.TODO, "start", empty)
        done = workflow.transition(in_progress, "complete", empty)
        reopened = workflow.transition(done, "reopen", empty)

        self.assertIs(reopened, ActionItemLifecycle.IN_PROGRESS)
        with self.assertRaisesRegex(WorkflowTransitionError, "requires a reason"):
            workflow.transition(ActionItemLifecycle.TODO, "cancel", empty)
        self.assertIs(
            workflow.transition(
                ActionItemLifecycle.IN_PROGRESS,
                "cancel",
                ActionItemTransitionContext(reason="整改动作不再适用"),
            ),
            ActionItemLifecycle.CANCELLED,
        )

    def test_scenario_data_validation_is_version_owned(self) -> None:
        self.assertEqual(
            (),
            PROCESS_REVIEW_V1.validate_case_input(
                {"area_code": "ASSY", "review_type": "routine"}
            ),
        )
        self.assertEqual(
            (),
            PROCESS_REVIEW_V1.validate_finding_input(
                {
                    "issue_type": "process_control",
                    "project_category": "onsite_management",
                }
            ),
        )
        self.assertIn(
            "area_code must be a non-blank string",
            PROCESS_REVIEW_V1.validate_case_input({"area_code": "", "review_type": "routine"}),
        )
        self.assertIn(
            "project_category must be a non-blank string",
            PROCESS_REVIEW_V1.validate_finding_input({"issue_type": "process_control"}),
        )

    def test_submission_policy_models_plan_completion_and_verification_rounds(self) -> None:
        policy = PROCESS_REVIEW_V1.submission_policy

        self.assertEqual(
            (),
            policy.validate_submission(
                SubmissionPurpose.RECTIFICATION,
                {"stage": "plan", "root_cause": "换线后未及时更新状态卡"},
            ),
        )
        self.assertEqual(
            (),
            policy.validate_submission(
                SubmissionPurpose.RECTIFICATION,
                {"stage": "completion", "comment": "整改完成，请审核"},
            ),
        )
        self.assertEqual(
            (),
            policy.validate_submission(
                SubmissionPurpose.VERIFICATION,
                {"result": "approved", "comment": "验收通过"},
            ),
        )
        self.assertIn(
            "comment must be a non-blank string",
            policy.validate_submission(
                SubmissionPurpose.VERIFICATION,
                {"result": "rejected", "comment": ""},
            ),
        )

    def test_authorization_separates_department_visibility_from_explicit_write_roles(self) -> None:
        policy = PROCESS_REVIEW_V1.authorization
        department_only = AuthorizationContext(
            department_finding_role_keys=frozenset({"responsible_department"})
        )
        owner = AuthorizationContext(explicit_finding_role_keys=frozenset({"owner"}))
        collaborator = AuthorizationContext(
            explicit_finding_role_keys=frozenset({"collaborator"}),
            action_assignment_roles=frozenset({AssignmentRole.COLLABORATOR}),
        )

        self.assertTrue(policy.allows(ProcessReviewPermission.VIEW_CASE, department_only))
        self.assertFalse(
            policy.allows(ProcessReviewPermission.SUBMIT_RECTIFICATION, department_only)
        )
        self.assertTrue(policy.allows(ProcessReviewPermission.CREATE_ACTION, owner))
        self.assertTrue(policy.allows(ProcessReviewPermission.SUBMIT_RECTIFICATION, owner))
        self.assertFalse(policy.allows(ProcessReviewPermission.CREATE_ACTION, collaborator))
        self.assertTrue(
            policy.allows(ProcessReviewPermission.UPDATE_ASSIGNED_ACTION, collaborator)
        )

    def test_authorization_uses_business_roles_not_platform_administrator_status(self) -> None:
        policy = PROCESS_REVIEW_V1.authorization
        lead = AuthorizationContext(case_role_keys=frozenset({"lead"}))
        reviewer = AuthorizationContext(case_role_keys=frozenset({"reviewer"}))
        observer = AuthorizationContext(case_role_keys=frozenset({"observer"}))
        no_business_relationship = AuthorizationContext()

        self.assertTrue(policy.allows(ProcessReviewPermission.TRANSITION_CASE, lead))
        self.assertTrue(policy.allows(ProcessReviewPermission.VERIFY_FINDING, reviewer))
        self.assertTrue(policy.allows(ProcessReviewPermission.VIEW_CASE, observer))
        self.assertFalse(policy.allows(ProcessReviewPermission.CREATE_FINDING, observer))
        self.assertFalse(
            policy.allows(ProcessReviewPermission.VERIFY_FINDING, no_business_relationship)
        )

    def test_review_core_contains_no_process_review_branching(self) -> None:
        repository_root = Path(__file__).resolve().parents[3]
        review_core = repository_root / "src" / "easyaudit_next" / "review_core"
        violations = [
            str(path.relative_to(repository_root))
            for path in review_core.rglob("*.py")
            if "process_review" in path.read_text(encoding="utf-8")
        ]

        self.assertEqual([], violations)
