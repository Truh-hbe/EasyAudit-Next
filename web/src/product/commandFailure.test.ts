import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/client'
import { ruleError } from '../api/ruleErrorFixture'
import { classifyCommandFailure, failureNeedsRefresh } from './commandFailure'

const classify = (error: unknown, fields: Record<string, string> = {}) => classifyCommandFailure(error, { label: '开始整改项', fields })

describe('classifyCommandFailure', () => {
  it('treats 401 as a session matter with no page text', () => {
    expect(classify(new ApiError(401, 'x'))).toEqual({ kind: 'session', message: '', fieldErrors: {} })
  })

  it('keeps 403/404 distinct and never reveals whether the object exists', () => {
    const forbidden = classify(new ApiError(403, 'Finding owner role required'))
    expect(forbidden).toMatchObject({ kind: 'forbidden', message: '当前账号没有执行此操作的权限。' })
    expect(forbidden.message).not.toContain('owner')
    expect(classify(new ApiError(404, 'secret detail'))).toMatchObject({ kind: 'gone', message: '内容不存在或无权访问' })
  })

  it('reads Retry-After for 429/503 and asks for a manual retry', () => {
    const failure = classify(new ApiError(429, 'slow', 30))
    expect(failure.kind).toBe('retry-later')
    expect(failure.message).toContain('30 秒后手动重试')
    expect(classify(new ApiError(503, 'down')).message).toContain('稍后手动重试')
  })

  it('maps 422 field errors onto labelled fields in Chinese and keeps the rest as page text', () => {
    const fields = { root_cause: '根本原因', title: '标题' }
    const onlyFields = classify(
      ruleError(422, 'request.invalid', {}, [{ field: 'root_cause', code: 'required', params: {} }]),
      fields,
    )
    expect(onlyFields).toEqual({ kind: 'rejected', message: '', fieldErrors: { root_cause: '请填写根本原因' } })

    const withUnlabelled = classify(
      ruleError(422, 'request.invalid', {}, [
        { field: 'title', code: 'too_long', params: { max: 300 } },
        { field: 'other_field', code: 'required', params: {} },
      ]),
      fields,
    )
    expect(withUnlabelled.fieldErrors).toEqual({ title: '标题不能超过 300 个字符' })
    expect(withUnlabelled.message).toContain('提交内容不符合要求')
  })

  it('does not match a field that is not labelled, even by a similar name', () => {
    const failure = classify(ruleError(422, 'request.invalid', {}, [{ field: 'my_reason_x', code: 'required', params: {} }]), {
      reason: '原因',
    })
    expect(failure.fieldErrors).toEqual({})
  })

  it('maps a rule code to Chinese with role names, and never shows the English detail', () => {
    const failure = classify(
      ruleError(422, 'finding.missing_participant_roles', { roles: ['responsible_department', 'owner'] }),
    )
    expect(failure.kind).toBe('rejected')
    expect(failure.message).toBe('签发前需要先指定：责任部门、整改负责人。')
    expect(failure.message).not.toContain('Backend')
  })

  it('uses a generic Chinese message for unknown, missing or malformed codes', () => {
    for (const error of [
      ruleError(422, 'future.unknown_code'),
      ruleError(422, null),
      new ApiError(422, 'root_cause is required'),
      new ApiError(422, 'Request failed with HTTP 422'),
    ]) {
      const failure = classify(error)
      expect(failure.message).toBe('开始整改项不满足当前规则，未完成。')
      expect(failure.fieldErrors).toEqual({})
    }
    expect(classify(ruleError(422, 'finding.missing_participant_roles', { roles: ['ghost'] })).message).toBe(
      '签发前需要先指定：未知角色。',
    )
  })

  it('reports every 409 as a possible change without classifying or showing detail', () => {
    for (const detail of ['Concurrent Finding transition', '(psycopg.errors.UniqueViolation) duplicate key', 'secret']) {
      const failure = classify(new ApiError(409, detail))
      expect(failure.kind).toBe('conflict')
      expect(failure.message).toContain('开始整改项未完成')
      expect(failure.message).not.toContain(detail)
      expect(failureNeedsRefresh(failure)).toBe(true)
    }
  })

  it('reports network failures and 5xx as unconfirmed, and 413/415 as upload limits', () => {
    expect(classify(new TypeError('Failed to fetch')).kind).toBe('unknown-result')
    expect(classify(new ApiError(500, 'boom')).message).toContain('未确认')
    expect(classify(new ApiError(413, 'big')).kind).toBe('too-large')
    expect(classify(new ApiError(415, 'type')).kind).toBe('type-not-allowed')
  })

  it('shows no backend detail for any status; other 4xx get a neutral message', () => {
    for (const status of [400, 405, 418]) {
      const failure = classify(new ApiError(status, 'internal role detail'))
      expect(failure.kind).toBe('rejected')
      expect(failure.message).not.toContain('internal role detail')
      expect(failure.message).toContain('开始整改项')
    }
  })

  it('refreshes only when server truth may have changed', () => {
    expect(failureNeedsRefresh(classify(new ApiError(409, 'x')))).toBe(true)
    expect(failureNeedsRefresh(classify(new ApiError(429, 'x')))).toBe(false)
    expect(failureNeedsRefresh(classify(new ApiError(413, 'x')))).toBe(false)
  })
})
