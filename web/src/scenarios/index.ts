import { PROCESS_REVIEW_V1_UI } from './processReviewV1'
import { ScenarioUiRegistry } from './registry'
import type {
  ScenarioCaseAdapter,
  ScenarioFindingAdapter,
  ScenarioUiAdapter,
} from './registry'

const scenarioRegistry = new ScenarioUiRegistry<ScenarioUiAdapter>()
scenarioRegistry.register('process_review', 1, PROCESS_REVIEW_V1_UI)

export function resolveCaseScenarioAdapter(
  scenarioKey: string,
  scenarioVersion: number,
): ScenarioCaseAdapter | undefined {
  return scenarioRegistry.resolve(scenarioKey, scenarioVersion)
}

export function resolveFindingScenarioAdapter(
  scenarioKey: string,
  scenarioVersion: number,
): ScenarioFindingAdapter | undefined {
  return scenarioRegistry.resolve(scenarioKey, scenarioVersion)
}
