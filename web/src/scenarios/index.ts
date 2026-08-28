import { PROCESS_REVIEW_V1_UI } from './processReviewV1'
import { ScenarioUiRegistry } from './registry'
import type { ScenarioCaseAdapter } from './registry'

const caseScenarioRegistry = new ScenarioUiRegistry<ScenarioCaseAdapter>()
caseScenarioRegistry.register('process_review', 1, PROCESS_REVIEW_V1_UI)

export function resolveCaseScenarioAdapter(
  scenarioKey: string,
  scenarioVersion: number,
): ScenarioCaseAdapter | undefined {
  return caseScenarioRegistry.resolve(scenarioKey, scenarioVersion)
}
