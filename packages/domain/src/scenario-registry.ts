import type { Scenario, ScenarioKey } from "./model.ts";

export interface ScenarioPolicy {
  readonly scenario: Scenario;
  readonly caseRoleKeys: readonly string[];
  readonly findingParticipantRoleKeys: readonly string[];
  validateCaseInput(input: Readonly<Record<string, unknown>>): readonly string[];
}

export class ScenarioRegistry {
  readonly #policies = new Map<ScenarioKey, ScenarioPolicy>();

  register(policy: ScenarioPolicy): void {
    const current = this.#policies.get(policy.scenario.key);
    if (current && current.scenario.version >= policy.scenario.version) {
      throw new Error(`Scenario version must increase: ${policy.scenario.key}`);
    }
    this.#policies.set(policy.scenario.key, policy);
  }

  get(key: ScenarioKey): ScenarioPolicy {
    const policy = this.#policies.get(key);
    if (!policy || !policy.scenario.enabled) {
      throw new Error(`Scenario is not available: ${key}`);
    }
    return policy;
  }
}
