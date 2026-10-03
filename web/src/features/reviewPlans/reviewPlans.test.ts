import { describe, expect, it, vi } from 'vitest'

import { ApiError, isIdempotencyKeyReuse } from '../../api/client'
import { resolveCaseScenarioAdapter } from '../../scenarios'
import {
  buildCaseCreateInput,
  canCreateCase,
  canSubmitCase,
  executeCaseSubmission,
  isDefinitiveRejection,
} from './ReviewCaseCreatePage'
import {
  canSubmitPlan,
  executePlanSubmission,
  isDefinitivePlanRejection,
} from './ReviewPlanCreatePage'
import type { ReviewCaseResponse, ReviewPlanResponse } from '../../api/product'

describe('M5.2 plan-first creation contracts', () => {
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

  it('treats a 4xx response as definitive but a transport error or 5xx as ambiguous', () => {
    expect(isDefinitiveRejection(new ApiError(422, 'invalid'))).toBe(true)
    expect(isDefinitiveRejection(new ApiError(409, 'conflict'))).toBe(true)
    expect(isDefinitiveRejection(new TypeError('network disconnected'))).toBe(false)
    expect(isDefinitiveRejection(new ApiError(500, 'Internal Server Error'))).toBe(false)
    expect(isDefinitivePlanRejection(new ApiError(422, 'invalid'))).toBe(true)
    expect(isDefinitivePlanRejection(new TypeError('network disconnected'))).toBe(false)
    expect(isDefinitivePlanRejection(new ApiError(503, 'unavailable', 30))).toBe(false)
  })

  it('says an unknown outcome is unconfirmed and that nothing is retried automatically', async () => {
    const plan = await executePlanSubmission(() => Promise.reject(new ApiError(500, 'boom')))
    const reviewCase = await executeCaseSubmission(() => Promise.reject(new TypeError('network disconnected')))
    for (const state of [plan.state, reviewCase.state]) {
      expect(state.status).toBe('unknown')
      expect('message' in state && state.message).toContain('未确认是否成功')
      expect('message' in state && state.message).toContain('不会自动再次提交')
    }
  })

  it('maps 422 segments that start with a field name onto that field and keeps the rest', async () => {
    const detail = 'review_type must be a non-blank string; area_code must not contain surrounding whitespace; plan is closed'
    const { state } = await executeCaseSubmission(
      () => Promise.reject(new ApiError(422, detail)),
      ['title', 'area_code', 'review_type'],
    )
    expect(state).toEqual({
      status: 'rejected',
      message: 'plan is closed',
      fieldErrors: {
        review_type: 'review_type must be a non-blank string',
        area_code: 'area_code must not contain surrounding whitespace',
      },
    })
    const unmapped = await executeCaseSubmission(() => Promise.reject(new ApiError(422, 'plan is closed')), ['title'])
    expect(unmapped.state).toEqual({ status: 'rejected', message: 'plan is closed', fieldErrors: {} })
    // 字段名只按完整标识匹配，不会误中更长的名字。
    const partial = await executePlanSubmission(() => Promise.reject(new ApiError(422, 'subtitle is too long')))
    expect(partial.state).toMatchObject({ status: 'rejected', fieldErrors: {} })
  })

  it('shows the Retry-After wait for 429 and keeps other 409 conflicts apart from key reuse', async () => {
    const limited = await executePlanSubmission(() => Promise.reject(new ApiError(429, 'Too many requests', 30)))
    expect(limited.state).toMatchObject({ status: 'rejected' })
    expect('message' in limited.state && limited.state.message).toContain('30 秒')
    const conflict = await executePlanSubmission(() => Promise.reject(new ApiError(409, 'Scenario is retired')))
    expect('message' in conflict.state && conflict.state.message).toContain('Scenario is retired')
    expect('message' in conflict.state && conflict.state.message).not.toContain('不一致')
  })

  it('allows a manual Plan retry after an ambiguous outcome, never an automatic one', async () => {
    const plan = { id: 'plan-123' } as ReviewPlanResponse
    const request = vi
      .fn<() => Promise<ReviewPlanResponse>>()
      .mockRejectedValueOnce(new TypeError('network disconnected'))
      .mockResolvedValueOnce(plan)
    const first = await executePlanSubmission(request)

    expect(request).toHaveBeenCalledTimes(1)
    expect(first.state.status).toBe('unknown')
    expect(canSubmitPlan(first.state)).toBe(true)
    expect(canSubmitPlan({ status: 'submitting' })).toBe(false)
    expect((await executePlanSubmission(request)).plan).toBe(plan)
    expect(request).toHaveBeenCalledTimes(2)
  })

  it('tells the user to refresh when the Idempotency-Key was reused by a different request', async () => {
    const reuse = new ApiError(409, 'Idempotency-Key reused with a different request')
    expect(isIdempotencyKeyReuse(reuse)).toBe(true)
    expect(isIdempotencyKeyReuse(new ApiError(409, 'stale lifecycle'))).toBe(false)
    const plan = await executePlanSubmission(() => Promise.reject(reuse))
    const reviewCase = await executeCaseSubmission(() => Promise.reject(reuse))
    for (const state of [plan.state, reviewCase.state]) {
      expect(state.status).toBe('rejected')
      expect('message' in state && state.message).toContain('刷新')
    }
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

  it('allows a manual Case retry after ambiguity and after a definitive rejection', async () => {
    const reviewCase = { id: 'case-123' } as ReviewCaseResponse
    const request = vi
      .fn<() => Promise<ReviewCaseResponse>>()
      .mockRejectedValueOnce(new TypeError('network disconnected'))
      .mockResolvedValueOnce(reviewCase)
    const first = await executeCaseSubmission(request)

    expect(request).toHaveBeenCalledTimes(1)
    expect(first.state.status).toBe('unknown')
    expect(canSubmitCase(first.state)).toBe(true)
    expect(canSubmitCase({ status: 'submitting' })).toBe(false)
    expect((await executeCaseSubmission(request)).reviewCase).toBe(reviewCase)
    expect(request).toHaveBeenCalledTimes(2)

    const retryRequest = vi
      .fn<() => Promise<ReviewCaseResponse>>()
      .mockRejectedValueOnce(new ApiError(422, 'invalid'))
      .mockResolvedValueOnce(reviewCase)
    const rejected = await executeCaseSubmission(retryRequest)
    expect(rejected.state.status).toBe('rejected')
    expect(canSubmitCase(rejected.state)).toBe(true)
    expect((await executeCaseSubmission(retryRequest)).reviewCase).toBe(reviewCase)
    expect(retryRequest).toHaveBeenCalledTimes(2)
  })

  it('does not create a Case when no exact adapter exists', () => {
    const request = vi.fn<() => Promise<ReviewCaseResponse>>()
    const unsupported = resolveCaseScenarioAdapter('process_review', 99)
    expect(unsupported).toBeUndefined()
    const state = { status: 'idle' } as const
    expect(canCreateCase(unsupported, state)).toBe(false)
    if (canCreateCase(unsupported, state)) void executeCaseSubmission(request)
    expect(request).not.toHaveBeenCalled()
  })
})
