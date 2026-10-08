import { describe, expect, it } from 'vitest'

import { FIELD_MESSAGES, RULE_MESSAGES, fieldMessage, ruleMessage } from './ruleMessages'

describe('rule messages', () => {
  it('renders every code in Chinese without Latin words', () => {
    for (const code of Object.keys(RULE_MESSAGES)) {
      const text = ruleMessage(code, { roles: ['owner'], max_rows: 100, min: 12, max: 20, operation: 'create' }, '签发发现项')
      expect(text, code).toMatch(/[一-鿿]/)
      expect(text, code).not.toMatch(/[A-Za-z]{2,}/)
    }
    for (const code of Object.keys(FIELD_MESSAGES)) {
      const text = fieldMessage(code, 'title', '标题', { max: 300, min: 1 })
      expect(text, code).toMatch(/[一-鿿]/)
      expect(text, code).not.toMatch(/[A-Za-z]{2,}/)
    }
  })

  it('degrades gracefully when params are missing or of the wrong type', () => {
    expect(ruleMessage('finding.missing_participant_roles', {}, 'x')).toBe('签发前需要先指定：所需角色。')
    expect(ruleMessage('export.row_limit_exceeded', { max_rows: 'many' }, 'x')).toContain('导出行数超过')
    expect(fieldMessage('too_long', 'title', '标题', {})).toBe('标题过长')
  })

  it('falls back to the generic message for unknown codes, including inherited object keys', () => {
    expect(ruleMessage('constructor', {}, '导出')).toBe('导出不满足当前规则，未完成。')
    expect(ruleMessage(null, {}, '导出')).toBe('导出不满足当前规则，未完成。')
    expect(fieldMessage('toString', 'title', '标题', {})).toBe('标题不符合要求')
  })

  it('puts the end-before-start range error on the end field', () => {
    expect(fieldMessage('range', 'planned_end_at', '活动结束时间', {})).toBe('活动结束时间不能早于开始时间')
  })
})
