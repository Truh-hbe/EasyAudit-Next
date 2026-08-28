import { describe, expect, it } from 'vitest'

import { resolveCaseScenarioAdapter } from './index'
import { ScenarioUiRegistry } from './registry'

describe('ScenarioUiRegistry exact version lookup', () => {
  it('never falls back to another version', () => {
    const registry = new ScenarioUiRegistry<string>()
    registry.register('process_review', 1, 'AdapterV1')
    registry.register('process_review', 2, 'AdapterV2')

    expect(registry.resolve('process_review', 1)).toBe('AdapterV1')
    expect(registry.resolve('process_review', 2)).toBe('AdapterV2')
    expect(registry.resolve('process_review', 99)).toBeUndefined()
    expect(registry.resolve('other', 1)).toBeUndefined()
  })

  it('production registry exposes only the exact process_review@1 adapter', () => {
    expect(resolveCaseScenarioAdapter('process_review', 1)).toBeDefined()
    expect(resolveCaseScenarioAdapter('process_review', 99)).toBeUndefined()
  })
})
