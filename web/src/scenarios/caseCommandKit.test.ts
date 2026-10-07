import { describe, expect, it } from 'vitest'

import type { ReviewCaseLifecycle } from '../api/product'
import { resolveCaseScenarioAdapter, resolveFindingScenarioAdapter } from '.'
import { standardCaseCommands } from './caseCommandKit'

const EXPECTED: Record<ReviewCaseLifecycle, string[]> = {
  draft: ['schedule', 'cancel'],
  scheduled: ['start', 'cancel'],
  in_progress: ['finish_fieldwork'],
  awaiting_closure: ['close'],
  closed: [],
  cancelled: [],
}

describe('case lifecycle commands', () => {
  for (const key of ['process_review', 'compliance_review']) {
    it(`${key}@1 declares the state machine's commands per lifecycle`, () => {
      const adapter = resolveCaseScenarioAdapter(key, 1)
      for (const [lifecycle, actions] of Object.entries(EXPECTED)) {
        expect(adapter?.caseCommands(lifecycle as ReviewCaseLifecycle).map((command) => command.action)).toEqual(actions)
      }
    })

    it(`${key}@1 only allows creating findings while in progress`, () => {
      const adapter = resolveFindingScenarioAdapter(key, 1)
      for (const lifecycle of Object.keys(EXPECTED) as ReviewCaseLifecycle[]) {
        expect(adapter?.canCreateFinding(lifecycle)).toBe(lifecycle === 'in_progress')
      }
    })
  }

  it('commands that need a reason are the destructive ones only', () => {
    const reasons = (['draft', 'scheduled', 'in_progress', 'awaiting_closure'] as const)
      .flatMap((lifecycle) => standardCaseCommands(lifecycle))
      .filter((command) => command.mode === 'reason')
    expect(reasons.map((command) => command.action)).toEqual(['cancel', 'cancel'])
  })
})
