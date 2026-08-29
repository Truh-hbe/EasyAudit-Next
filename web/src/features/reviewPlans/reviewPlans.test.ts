import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import { resolveCaseScenarioAdapter } from '../../scenarios'
import {
  buildCaseCreateInput,
  canSubmitCase,
  executeCaseSubmission,
  isDefinitiveRejection,
} from './ReviewCaseCreatePage'
import {
  canSubmitPlan,
  dateInputToApi,
  executePlanSubmission,
  isDefinitivePlanRejection,
} from './ReviewPlanCreatePage'
import type { ReviewCaseResponse, ReviewPlanResponse } from '../../api/product'

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
    expect(isDefinitivePlanRejection(new ApiError(422, 'invalid'))).toBe(true)
    expect(isDefinitivePlanRejection(new TypeError('network disconnected'))).toBe(false)
  })

  it('blocks a second Plan mutation after an ambiguous outcome', async () => {
    const request = vi
      .fn<() => Promise<ReviewPlanResponse>>()
      .mockRejectedValueOnce(new TypeError('network disconnected'))
    const first = await executePlanSubmission(request)

    expect(request).toHaveBeenCalledTimes(1)
    expect(first.state.status).toBe('unknown')
    expect(canSubmitPlan(first.state)).toBe(false)
    if (canSubmitPlan(first.state)) await executePlanSubmission(request)
    expect(request).toHaveBeenCalledTimes(1)
  })

  it('allows a definitive Plan rejection to be corrected and retried', async () => {
    const plan = { id: 'plan-123' } as ReviewPlanResponse
    const request = vi
      .fn<() => Promise<ReviewPlanResponse>>()
      .mockRejectedValueOnce(new ApiError(422, 'invalid'))
      .mockResolvedValueOnce(plan)
    const first = await executePlanSubmission(request)

    expect(first.state.status).toBe('rejected')
    expect(canSubmitPlan(first.state)).toBe(true)
    const second = await executePlanSubmission(request)
    expect(second.plan).toBe(plan)
    expect(request).toHaveBeenCalledTimes(2)
  })

  it('blocks a second Case mutation after ambiguity and permits only definitive retry', async () => {
    const request = vi
      .fn<() => Promise<ReviewCaseResponse>>()
      .mockRejectedValueOnce(new TypeError('network disconnected'))
    const first = await executeCaseSubmission(request)

    expect(request).toHaveBeenCalledTimes(1)
    expect(first.state.status).toBe('unknown')
    expect(canSubmitCase(first.state)).toBe(false)
    if (canSubmitCase(first.state)) await executeCaseSubmission(request)
    expect(request).toHaveBeenCalledTimes(1)

    const reviewCase = { id: 'case-123' } as ReviewCaseResponse
    const retryRequest = vi
      .fn<() => Promise<ReviewCaseResponse>>()
      .mockRejectedValueOnce(new ApiError(422, 'invalid'))
      .mockResolvedValueOnce(reviewCase)
    const rejected = await executeCaseSubmission(retryRequest)
    expect(rejected.state.status).toBe('rejected')
    expect(canSubmitCase(rejected.state)).toBe(true)
    const retry = await executeCaseSubmission(retryRequest)
    expect(retry.reviewCase).toBe(reviewCase)
    expect(retryRequest).toHaveBeenCalledTimes(2)
  })

  it('does not create a Case when no exact adapter exists', () => {
    const request = vi.fn()
    const unsupported = resolveCaseScenarioAdapter('process_review', 99)
    expect(unsupported).toBeUndefined()
    expect(request).not.toHaveBeenCalled()
  })
})
