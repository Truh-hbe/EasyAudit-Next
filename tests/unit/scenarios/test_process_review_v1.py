from pathlib import Path
from unittest import TestCase

from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.review_core.domain.models import (
    ActionItemLifecycle,
    FindingLifecycle,
    ReviewCaseLifecycle,
    ScenarioKey,
    ScenarioVersion,
    SubmissionPurpose,
)
from easyaudit_next.review_core.domain.planning_policy import (
    CORE_REVIEW_PLANNING_AUTHORIZATION,
    PlanningAuthorizationContext,
    ReviewPlanningPermission,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActionItemTransitionContext,
    ActorKind,
    AuthorizationContext,
    FindingTransitionContext,
    PermissionSource,
    ReviewCaseTransitionContext,
    RoleGrant,
    RoleSpecification,
    SubmissionDecisionError,
    SubmissionRequest,
    WorkflowTransitionError,
)
from easyaudit_next.scenarios.process_review import (
    PROCESS_REVIEW_V1,
    ProcessReviewPermission,
    ProcessReviewSubmissionAction,
)


def _role_spec(
    specs: tuple[RoleSpecification, ...],
    key: str,
) -> RoleSpecification:
    return next(spec for spec in specs if spec.key == key)


def _direct_user_grant(role_key: str) -> RoleGrant:
    return RoleGrant(
        role_key=role_key,
        actor_kind=ActorKind.USER,
        source=PermissionSource.DIRECT,
    )


class ProcessReviewV1Test(TestCase):
    def test_composition_root_registers_exact_versioned_policy(self) -> None:
        registry = build_scenario_registry()

        self.assertIs(
            registry.get(ScenarioKey("process_review"), ScenarioVersion(1)),
            PROCESS_REVIEW_V1,
        )

    def test_review_plan_creation_is_core_owned_and_requires_active_org_user(self) -> None:
        policy = CORE_REVIEW_PLANNING_AUTHORIZATION

        self.assertTrue(
            policy.allows(
                ReviewPlanningPermission.CREATE_REVIEW_PLAN,
                PlanningAuthorizationContext(is_active_organization_user=True),
            )
        )
        self.assertFalse(
            policy.allows(
                ReviewPlanningPermission.CREATE_REVIEW_PLAN,
                PlanningAuthorizationContext(is_active_organization_user=False),
            )
        )

    def test_case_creation_is_scenario_owned_and_creator_becomes_lead_atomically(self) -> None:
        authorization = PROCESS_REVIEW_V1.authorization
        decision = PROCESS_REVIEW_V1.case_creation.decision()

        self.assertTrue(
            authorization.allows(
                ProcessReviewPermission.CREATE_CASE,
                AuthorizationContext(is_active_organization_user=True),
            )
        )
        self.assertFalse(
            authorization.allows(
                ProcessReviewPermission.CREATE_CASE,
                AuthorizationContext(is_active_organization_user=False),
            )
        )
        self.assertEqual(ProcessReviewPermission.CREATE_CASE, decision.required_permission)
        self.assertIs(decision.initial_lifecycle, ReviewCaseLifecycle.DRAFT)
        self.assertEqual(("lead",), decision.creator_role_keys)
        self.assertEqual("review_case.created", decision.activity_event_type)
        self.assertTrue(decision.requires_atomic_membership)

    def test_role_specs_freeze_actor_types_and_permission_sources(self) -> None:
        responsible = _role_spec(
            PROCESS_REVIEW_V1.finding_participant_role_specs,
            "responsible_department",
        )
        owner = _role_spec(PROCESS_REVIEW_V1.finding_participant_role_specs, "owner")
        collaborator = _role_spec(
            PROCESS_REVIEW_V1.finding_participant_role_specs,
            "collaborator",
        )
        primary_action = _role_spec(
            PROCESS_REVIEW_V1.action_assignee_role_specs,
            "primary",
        )

        self.assertEqual(frozenset({ActorKind.DEPARTMENT}), responsible.allowed_actor_kinds)
        self.assertEqual(
            frozenset({PermissionSource.DEPARTMENT_MEMBERSHIP}),
            responsible.permission_sources,
        )
        for spec in (owner, collaborator, primary_action):
            self.assertEqual(frozenset({ActorKind.USER}), spec.allowed_actor_kinds)
            self.assertEqual(frozenset({PermissionSource.DIRECT}), spec.permission_sources)

        self.assertFalse(
            primary_action.accepts_grant(
                RoleGrant(
                    role_key="primary",
                    actor_kind=ActorKind.DEPARTMENT,
                    source=PermissionSource.DEPARTMENT_MEMBERSHIP,
                )
            )
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
            workflow.transition(
                ReviewCaseLifecycle.DRAFT,
                "cancel",
                ReviewCaseTransitionContext(),
            )

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
            PROCESS_REVIEW_V1.validate_case_input(
                {"area_code": "", "review_type": "routine"}
            ),
        )
        self.assertIn(
            "project_category must be a non-blank string",
            PROCESS_REVIEW_V1.validate_finding_input({"issue_type": "process_control"}),
        )

    def test_submission_policy_returns_atomic_plan_and_completion_decisions(self) -> None:
        policy = PROCESS_REVIEW_V1.submission_policy

        plan = policy.decide(
            SubmissionRequest(
                current_lifecycle=FindingLifecycle.RECTIFYING,
                action=ProcessReviewSubmissionAction.SUBMIT_PLAN,
                purpose=SubmissionPurpose.RECTIFICATION,
                payload={"stage": "plan", "root_cause": "换线后未及时更新状态卡"},
            )
        )
        self.assertEqual(ProcessReviewPermission.SUBMIT_RECTIFICATION, plan.required_permission)
        self.assertIs(plan.target_lifecycle, FindingLifecycle.RECTIFYING)
        self.assertEqual("finding.rectification_plan_submitted", plan.activity_event_type)
        self.assertTrue(plan.requires_atomic_write)

        completion = policy.decide(
            SubmissionRequest(
                current_lifecycle=FindingLifecycle.RECTIFYING,
                action=ProcessReviewSubmissionAction.SUBMIT_FOR_VERIFICATION,
                purpose=SubmissionPurpose.RECTIFICATION,
                payload={"stage": "completion", "comment": "整改完成，请审核"},
                transition_context=FindingTransitionContext(
                    non_cancelled_action_count=2,
                    all_non_cancelled_actions_done=True,
                ),
            )
        )
        self.assertIs(completion.target_lifecycle, FindingLifecycle.VERIFYING)
        self.assertEqual(
            "finding.submitted_for_verification",
            completion.activity_event_type,
        )
        self.assertTrue(completion.requires_atomic_write)

    def test_submission_policy_rejects_lifecycle_action_and_payload_mismatches(self) -> None:
        policy = PROCESS_REVIEW_V1.submission_policy

        with self.assertRaisesRegex(SubmissionDecisionError, "only be submitted"):
            policy.decide(
                SubmissionRequest(
                    current_lifecycle=FindingLifecycle.OPEN,
                    action=ProcessReviewSubmissionAction.SUBMIT_PLAN,
                    purpose=SubmissionPurpose.RECTIFICATION,
                    payload={"stage": "plan", "root_cause": "原因"},
                )
            )

        with self.assertRaisesRegex(SubmissionDecisionError, "stage 'plan'"):
            policy.decide(
                SubmissionRequest(
                    current_lifecycle=FindingLifecycle.RECTIFYING,
                    action=ProcessReviewSubmissionAction.SUBMIT_PLAN,
                    purpose=SubmissionPurpose.RECTIFICATION,
                    payload={"stage": "completion", "comment": "完成"},
                )
            )

        with self.assertRaisesRegex(SubmissionDecisionError, "result 'approved'"):
            policy.decide(
                SubmissionRequest(
                    current_lifecycle=FindingLifecycle.VERIFYING,
                    action=ProcessReviewSubmissionAction.APPROVE,
                    purpose=SubmissionPurpose.VERIFICATION,
                    payload={"result": "rejected", "comment": "不通过"},
                )
            )

        with self.assertRaisesRegex(WorkflowTransitionError, "at least one"):
            policy.decide(
                SubmissionRequest(
                    current_lifecycle=FindingLifecycle.RECTIFYING,
                    action=ProcessReviewSubmissionAction.SUBMIT_FOR_VERIFICATION,
                    purpose=SubmissionPurpose.RECTIFICATION,
                    payload={"stage": "completion", "comment": "完成"},
                )
            )

    def test_submission_policy_binds_verification_result_to_workflow_action(self) -> None:
        policy = PROCESS_REVIEW_V1.submission_policy

        approved = policy.decide(
            SubmissionRequest(
                current_lifecycle=FindingLifecycle.VERIFYING,
                action=ProcessReviewSubmissionAction.APPROVE,
                purpose=SubmissionPurpose.VERIFICATION,
                payload={"result": "approved", "comment": "验收通过"},
            )
        )
        self.assertEqual(ProcessReviewPermission.VERIFY_FINDING, approved.required_permission)
        self.assertIs(approved.target_lifecycle, FindingLifecycle.CLOSED)
        self.assertEqual("finding.approved", approved.activity_event_type)

        rejected = policy.decide(
            SubmissionRequest(
                current_lifecycle=FindingLifecycle.VERIFYING,
                action=ProcessReviewSubmissionAction.REJECT,
                purpose=SubmissionPurpose.VERIFICATION,
                payload={"result": "rejected", "comment": "整改证据不足"},
            )
        )
        self.assertIs(rejected.target_lifecycle, FindingLifecycle.RECTIFYING)
        self.assertEqual("finding.rejected", rejected.activity_event_type)
        self.assertTrue(rejected.requires_atomic_write)

    def test_authorization_separates_department_visibility_from_direct_write_roles(self) -> None:
        policy = PROCESS_REVIEW_V1.authorization
        department_only = AuthorizationContext(
            finding_role_grants=frozenset(
                {
                    RoleGrant(
                        role_key="responsible_department",
                        actor_kind=ActorKind.DEPARTMENT,
                        source=PermissionSource.DEPARTMENT_MEMBERSHIP,
                    )
                }
            )
        )
        owner = AuthorizationContext(
            finding_role_grants=frozenset({_direct_user_grant("owner")})
        )
        collaborator = AuthorizationContext(
            finding_role_grants=frozenset({_direct_user_grant("collaborator")}),
            action_role_grants=frozenset({_direct_user_grant("collaborator")}),
        )
        department_action = AuthorizationContext(
            action_role_grants=frozenset(
                {
                    RoleGrant(
                        role_key="primary",
                        actor_kind=ActorKind.DEPARTMENT,
                        source=PermissionSource.DEPARTMENT_MEMBERSHIP,
                    )
                }
            )
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
        self.assertFalse(
            policy.allows(ProcessReviewPermission.UPDATE_ASSIGNED_ACTION, department_action)
        )

    def test_authorization_uses_business_roles_not_platform_administrator_status(self) -> None:
        policy = PROCESS_REVIEW_V1.authorization
        lead = AuthorizationContext(
            case_role_grants=frozenset({_direct_user_grant("lead")})
        )
        reviewer = AuthorizationContext(
            case_role_grants=frozenset({_direct_user_grant("reviewer")})
        )
        observer = AuthorizationContext(
            case_role_grants=frozenset({_direct_user_grant("observer")})
        )
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
