import { describe, expect, it } from 'vitest'

import { ApiError } from '../../api/client'
import { resolveCaseScenarioAdapter } from '../../scenarios'
import { buildCaseCreateInput, isDefinitiveRejection } from './ReviewCaseCreatePage'
import { dateInputToApi } from './ReviewPlanCreatePage'

describe('M5.2 plan-first creation contracts', () => {
  it('converts optional local date input to an aware API value', () => {
    expect(dateInputToApi('')).toBeNull()
    expect(dateInputToApi('2026-08-30T09:30')).toBe(new Date('2026-08-30T09:30').toISOString())
    expect(dateInputToApi('not-a-date')).toBeNull()
  })

  it('builds the exact Case payload without Plan date inheritance', () => {
    const item = {
      scenario_key: 'process_review',
      scenario_version: 1,
      display_name: 'Process Review',
    }
    const adapter = resolveCaseScenarioAdapter(item.scenario_key, item.scenario_version)
    expect(adapter).toBeDefined()
    if (adapter === undefined) return

    expect(
      buildCaseCreateInput(
        'plan-123',
        item,
        'Case title',
        adapter,
        { area_code: 'area-a', review_type: 'standard' },
      ),
    ).toEqual({
      plan_id: 'plan-123',
      scenario_key: 'process_review',
      scenario_version: 1,
      title: 'Case title',
      scenario_data: { area_code: 'area-a', review_type: 'standard' },
    })
  })

  it('treats a server response as definitive but a transport error as ambiguous', () => {
    expect(isDefinitiveRejection(new ApiError(422, 'invalid'))).toBe(true)
    expect(isDefinitiveRejection(new TypeError('network disconnected'))).toBe(false)
  })
})
