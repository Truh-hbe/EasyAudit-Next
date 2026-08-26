from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from easyaudit_next.review_core.domain.models import Scenario, ScenarioKey, ScenarioVersion
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActionItemOperationPolicy,
    ActionItemWorkflowPolicy,
    AuthorizationPolicy,
    FindingOperationPolicy,
    FindingWorkflowPolicy,
    ReviewCaseCreationPolicy,
    ReviewCaseWorkflowPolicy,
    RoleSpecification,
    SubmissionPolicy,
)


class ScenarioPolicy(Protocol):
    @property
    def scenario(self) -> Scenario: ...

    @property
    def case_role_specs(self) -> tuple[RoleSpecification, ...]: ...

    @property
    def finding_participant_role_specs(self) -> tuple[RoleSpecification, ...]: ...

    @property
    def action_assignee_role_specs(self) -> tuple[RoleSpecification, ...]: ...

    @property
    def case_creation(self) -> ReviewCaseCreationPolicy: ...

    @property
    def case_workflow(self) -> ReviewCaseWorkflowPolicy: ...

    @property
    def finding_workflow(self) -> FindingWorkflowPolicy: ...

    @property
    def finding_operations(self) -> FindingOperationPolicy: ...

    @property
    def action_workflow(self) -> ActionItemWorkflowPolicy: ...

    @property
    def action_operations(self) -> ActionItemOperationPolicy: ...

    @property
    def authorization(self) -> AuthorizationPolicy: ...

    @property
    def submission_policy(self) -> SubmissionPolicy: ...

    def validate_case_input(self, payload: Mapping[str, object]) -> tuple[str, ...]: ...

    def validate_finding_input(self, payload: Mapping[str, object]) -> tuple[str, ...]: ...


@dataclass(slots=True)
class ScenarioRegistry:
    """Stores every immutable Scenario version needed to interpret historical cases."""

    _policies: dict[ScenarioKey, dict[ScenarioVersion, ScenarioPolicy]] = field(
        default_factory=dict
    )

    def register(self, policy: ScenarioPolicy) -> None:
        versions = self._policies.setdefault(policy.scenario.key, {})
        if policy.scenario.version in versions:
            raise ValueError(
                "Scenario version is already registered: "
                f"{policy.scenario.key}@{policy.scenario.version}"
            )
        versions[policy.scenario.version] = policy

    def get(self, key: ScenarioKey, version: ScenarioVersion) -> ScenarioPolicy:
        try:
            return self._policies[key][version]
        except KeyError as exc:
            raise LookupError(f"Scenario version is not registered: {key}@{version}") from exc

    def get_latest(self, key: ScenarioKey) -> ScenarioPolicy:
        try:
            enabled = [policy for policy in self._policies[key].values() if policy.scenario.enabled]
        except KeyError as exc:
            raise LookupError(f"Scenario is not registered: {key}") from exc
        if not enabled:
            raise LookupError(f"Scenario has no enabled version: {key}")
        return max(enabled, key=lambda policy: policy.scenario.version)
