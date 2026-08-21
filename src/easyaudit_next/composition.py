from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
from easyaudit_next.scenarios.process_review import PROCESS_REVIEW_V1


def build_scenario_registry() -> ScenarioRegistry:
    """Composition root for code-defined immutable Scenario policies."""

    registry = ScenarioRegistry()
    registry.register(PROCESS_REVIEW_V1)
    return registry
