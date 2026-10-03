import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/client'
import { classifyCommandFailure, failureNeedsRefresh } from './commandFailure'

const classify = (error: unknown, fields: string[] = []) => classifyCommandFailure(error, { label: '开始整改项', fields })

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

  it('maps 422 segments to fields and keeps the rest as page text', () => {
    const failure = classify(new ApiError(422, 'root_cause is required; something else'), ['root_cause'])
    expect(failure.fieldErrors).toEqual({ root_cause: 'root_cause is required' })
    expect(failure.message).toBe('something else')
    expect(classify(new ApiError(422, 'root_cause is required'), ['root_cause']).message).toBe('')
  })

  it('does not match a field name inside a longer identifier', () => {
    expect(classify(new ApiError(422, 'my_reason_x invalid'), ['reason']).fieldErrors).toEqual({})
  })

  it('splits 409 into lifecycle change, duplicate relation and unclassified conflict without leaking detail', () => {
    for (const detail of ['Concurrent Finding transition', 'Concurrent ActionItem transition', 'Concurrent ReviewCase transition']) {
      const failure = classify(new ApiError(409, detail))
      expect(failure.kind).toBe('changed')
      expect(failure.message).toContain('数据已变化，正在获取最新状态')
      expect(failure.message).not.toContain('Concurrent')
    }
    const duplicate = classify(
      new ApiError(409, '(psycopg.errors.UniqueViolation) duplicate key value violates unique constraint "uq_x"'),
    )
    expect(duplicate.kind).toBe('duplicate')
    expect(duplicate.message).toContain('已在列表中')
    expect(duplicate.message).not.toContain('uq_x')
    const other = classify(new ApiError(409, 'something unexpected: secret'))
    expect(other.kind).toBe('conflict')
    expect(other.message).toContain('冲突')
    expect(other.message).not.toContain('secret')
    for (const detail of ['Concurrent Finding transition', 'duplicate key', 'other']) {
      expect(failureNeedsRefresh(classify(new ApiError(409, detail)))).toBe(true)
    }
  })

  it('reports network failures and 5xx as unconfirmed, and 413/415 as upload limits', () => {
    expect(classify(new TypeError('Failed to fetch')).kind).toBe('unknown-result')
    expect(classify(new ApiError(500, 'boom')).message).toContain('未确认')
    expect(classify(new ApiError(413, 'big')).kind).toBe('too-large')
    expect(classify(new ApiError(415, 'type')).kind).toBe('type-not-allowed')
  })

  it('refreshes only when server truth may have changed', () => {
    expect(failureNeedsRefresh(classify(new ApiError(409, 'x')))).toBe(true)
    expect(failureNeedsRefresh(classify(new ApiError(429, 'x')))).toBe(false)
    expect(failureNeedsRefresh(classify(new ApiError(413, 'x')))).toBe(false)
  })
})
