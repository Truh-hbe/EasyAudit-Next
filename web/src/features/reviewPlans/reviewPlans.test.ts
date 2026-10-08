import { describe, expect, it, vi } from 'vitest'

import { ApiError, isIdempotencyKeyReuse } from '../../api/client'
import { ENGLISH_DETAIL, ruleError } from '../../api/ruleErrorFixture'
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

  it('includes Case dates only when given, as the exact ISO instants', () => {
    const item = { scenario_key: 'process_review', scenario_version: 1, display_name: 'Process Review' }
    const adapter = resolveCaseScenarioAdapter(item.scenario_key, item.scenario_version)
    if (adapter === undefined) throw new Error('adapter missing')
    const values = { area_code: 'area-a', review_type: 'standard' }
    const both = buildCaseCreateInput('p', item, 't', adapter, values, '2026-09-01T01:00:00.000Z', '2026-09-30T10:00:00.000Z')
    expect(both).toMatchObject({ planned_start_at: '2026-09-01T01:00:00.000Z', planned_end_at: '2026-09-30T10:00:00.000Z' })
    const endOnly = buildCaseCreateInput('p', item, 't', adapter, values, null, '2026-09-30T10:00:00.000Z')
    expect(endOnly).not.toHaveProperty('planned_start_at')
    expect(endOnly).toMatchObject({ planned_end_at: '2026-09-30T10:00:00.000Z' })
    expect(buildCaseCreateInput('p', item, 't', adapter, values, null, null)).not.toHaveProperty('planned_end_at')
  })

  it('maps the end-before-start 422 onto the end field', async () => {
    const { state } = await executeCaseSubmission(
      () => Promise.reject(ruleError(422, 'request.invalid', {}, [{ field: 'planned_end_at', code: 'range', params: {} }])),
      { planned_end_at: '活动结束时间', planned_start_at: '活动开始时间', title: '审查活动名称' },
    )
    expect(state).toEqual({
      status: 'rejected',
      message: '',
      fieldErrors: { planned_end_at: '活动结束时间不能早于开始时间' },
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

  it('maps 422 field errors onto fields in Chinese and never shows the English detail', async () => {
    const error = ruleError(422, 'request.invalid', {}, [
      { field: 'review_type', code: 'required', params: {} },
      { field: 'area_code', code: 'padded', params: {} },
      { field: 'unlabelled', code: 'required', params: {} },
    ])
    const { state } = await executeCaseSubmission(() => Promise.reject(error), {
      title: '审查活动名称',
      area_code: '区域代码',
      review_type: '审查类型',
    })
    expect(state).toMatchObject({
      status: 'rejected',
      fieldErrors: { review_type: '请填写审查类型', area_code: '区域代码首尾不能有空格' },
    })
    expect(JSON.stringify(state)).not.toContain(ENGLISH_DETAIL)

    const unknown = await executeCaseSubmission(() => Promise.reject(new ApiError(422, 'plan is closed')), { title: '审查活动名称' })
    expect(unknown.state).toEqual({
      status: 'rejected',
      message: '创建审查活动不满足当前规则，未完成。',
      fieldErrors: {},
    })
    const plan = await executePlanSubmission(() => Promise.reject(ruleError(422, 'rule.unspecified')))
    expect(plan.state).toMatchObject({ status: 'rejected', fieldErrors: {} })
  })

  it('shows the Retry-After wait for 429 and keeps other 409 conflicts apart from key reuse', async () => {
    const limited = await executePlanSubmission(() => Promise.reject(new ApiError(429, 'Too many requests', 30)))
    expect(limited.state).toMatchObject({ status: 'rejected' })
    expect('message' in limited.state && limited.state.message).toContain('30 秒')
    const conflict = await executePlanSubmission(() => Promise.reject(new ApiError(409, 'Scenario is retired')))
    expect('message' in conflict.state && conflict.state.message).toContain('与服务器当前状态冲突')
    expect('message' in conflict.state && conflict.state.message).not.toContain('Scenario is retired')
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
