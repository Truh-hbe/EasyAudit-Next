from dataclasses import dataclass
from typing import Mapping
from unittest import TestCase

from easyaudit_next.review_core.domain.models import Scenario, ScenarioKey, ScenarioVersion
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry


@dataclass(frozen=True)
class Policy:
    scenario: Scenario
    case_role_keys: tuple[str, ...] = ("lead", "reviewer")
    finding_participant_role_keys: tuple[str, ...] = (
        "rectification_owner",
        "verifier",
    )

    def validate_case_input(self, payload: Mapping[str, object]) -> tuple[str, ...]:
        return ()


def policy(version: int, *, enabled: bool = True) -> Policy:
    return Policy(
        scenario=Scenario(
            key=ScenarioKey("process_review"),
            version=ScenarioVersion(version),
            name="过程审查",
            enabled=enabled,
        )
    )


class ScenarioRegistryTest(TestCase):
    def test_registry_preserves_every_historical_version(self) -> None:
        registry = ScenarioRegistry()
        v1 = policy(1)
        v2 = policy(2)

        registry.register(v1)
        registry.register(v2)

        self.assertIs(registry.get(ScenarioKey("process_review"), ScenarioVersion(1)), v1)
        self.assertIs(registry.get(ScenarioKey("process_review"), ScenarioVersion(2)), v2)
        self.assertIs(registry.get_latest(ScenarioKey("process_review")), v2)

    def test_exact_version_lookup_survives_scenario_disablement(self) -> None:
        registry = ScenarioRegistry()
        disabled_history = policy(1, enabled=False)
        current = policy(2)
        registry.register(disabled_history)
        registry.register(current)

        self.assertIs(
            registry.get(ScenarioKey("process_review"), ScenarioVersion(1)),
            disabled_history,
        )
        self.assertIs(registry.get_latest(ScenarioKey("process_review")), current)

    def test_duplicate_version_is_rejected_instead_of_overwritten(self) -> None:
        registry = ScenarioRegistry()
        registry.register(policy(1))

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(policy(1))

    def test_unknown_exact_version_has_explicit_error(self) -> None:
        registry = ScenarioRegistry()

        with self.assertRaisesRegex(LookupError, "process_review@1"):
            registry.get(ScenarioKey("process_review"), ScenarioVersion(1))
