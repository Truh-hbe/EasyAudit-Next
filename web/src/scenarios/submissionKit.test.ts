import { describe, expect, it } from 'vitest'

import type { SubmissionPurpose, SubmissionResponse } from '../api/product'
import { resolveFindingScenarioAdapter } from '.'

function submission(purpose: SubmissionPurpose, payload: Record<string, unknown>): SubmissionResponse {
  return {
    id: 's1',
    organization_id: 'o1',
    case_id: 'c1',
    finding_id: 'f1',
    purpose,
    submitted_by: 'u1',
    submitted_at: '2026-10-01T00:00:00Z',
    payload,
  }
}

for (const key of ['process_review', 'compliance_review']) {
  describe(`${key}@1 submission view`, () => {
    const describe_ = resolveFindingScenarioAdapter(key, 1)!.describeSubmission

    it('labels the rectification plan root cause', () => {
      expect(describe_(submission('rectification', { stage: 'plan', root_cause: '校准缺失' }))).toEqual({
        heading: '整改计划',
        outcome: null,
        fields: [{ key: 'root_cause', label: '根本原因', value: '校准缺失' }],
        extras: [],
      })
    })

    it('labels the completion comment', () => {
      const view = describe_(submission('rectification', { stage: 'completion', comment: '已补做' }))
      expect(view.heading).toBe('整改完成说明')
      expect(view.fields).toEqual([{ key: 'comment', label: '整改完成说明', value: '已补做' }])
    })

    it('marks a rejection with its reason', () => {
      const view = describe_(submission('verification', { result: 'rejected', comment: '需补充校准确认' }))
      expect(view.heading).toBe('验证驳回')
      expect(view.outcome).toBe('rejected')
      expect(view.fields).toEqual([{ key: 'comment', label: '驳回原因', value: '需补充校准确认' }])
    })

    it('marks an approval without requiring a comment', () => {
      const view = describe_(submission('verification', { result: 'approved' }))
      expect(view).toMatchObject({ heading: '验证通过', outcome: 'approved', fields: [], extras: [] })
    })

    it('shows an empty payload as no content, not as an error', () => {
      const view = describe_(submission('rectification', {}))
      expect(view).toMatchObject({ heading: '整改提交', outcome: null, fields: [], extras: [] })
    })

    it('shows unknown fields as plain text and never expands structures', () => {
      const view = describe_(
        submission('rectification', {
          stage: 'plan',
          root_cause: 'x',
          note: '<img src=x onerror=alert(1)>',
          count: 3,
          nested: { secret: 'y' },
          empty: '  ',
          nothing: null,
        }),
      )
      expect(view.extras.map((item) => [item.label, item.value])).toEqual([
        ['其他内容（note）', '<img src=x onerror=alert(1)>'],
        ['其他内容（count）', '3'],
        ['其他内容（nested）', '（结构化内容，此处不展示）'],
      ])
    })

    it('does not guess a verification result it does not know', () => {
      const view = describe_(submission('verification', { result: 'maybe', comment: 'c' }))
      expect(view.outcome).toBeNull()
      expect(view.heading).toBe('验证结论')
      expect(view.extras.map((item) => item.value)).toEqual(['c'])
    })
  })
}
