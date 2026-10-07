import { describe, expect, it } from 'vitest'

import type { ActionItemLifecycle, FindingLifecycle, ReviewCaseLifecycle } from '../api/product'
import { resolveFindingScenarioAdapter } from '.'

const ACTIONS: ActionItemLifecycle[] = ['todo', 'in_progress', 'done', 'cancelled']

for (const key of ['process_review', 'compliance_review']) {
  describe(`${key}@1 action operations`, () => {
    const operations = resolveFindingScenarioAdapter(key, 1)!.actionOperations

    it('allows operations under a rectifying finding in an active case, except terminal assignee management', () => {
      for (const reviewCase of ['in_progress', 'awaiting_closure'] as ReviewCaseLifecycle[]) {
        for (const action of ACTIONS) {
          expect(operations({ action, finding: 'rectifying', reviewCase })).toEqual({
            blockedReason: null,
            writable: true,
            manageAssignees: action === 'todo' || action === 'in_progress',
            uploadEvidence: action !== 'cancelled',
          })
        }
      }
    })

    it('keeps a done action fully reopenable and evidence-capable while the finding is rectifying', () => {
      const result = operations({ action: 'done', finding: 'rectifying', reviewCase: 'in_progress' })
      expect(result.writable).toBe(true)
      expect(result.uploadEvidence).toBe(true)
      expect(result.manageAssignees).toBe(false)
    })

    it('closes every write when the finding is not rectifying, with an explanation', () => {
      for (const finding of ['open', 'verifying', 'closed', 'voided'] as FindingLifecycle[]) {
        for (const action of ACTIONS) {
          const result = operations({ action, finding, reviewCase: 'in_progress' })
          expect(result).toMatchObject({ writable: false, manageAssignees: false, uploadEvidence: false })
          expect(result.blockedReason).toBeTruthy()
        }
      }
      expect(operations({ action: 'done', finding: 'verifying', reviewCase: 'in_progress' }).blockedReason).toContain('已提交验证')
      expect(operations({ action: 'done', finding: 'closed', reviewCase: 'in_progress' }).blockedReason).toContain('重新打开发现项')
    })

    it('closes every write when the case is not active', () => {
      for (const reviewCase of ['draft', 'scheduled', 'closed', 'cancelled'] as ReviewCaseLifecycle[]) {
        const result = operations({ action: 'in_progress', finding: 'rectifying', reviewCase })
        expect(result).toMatchObject({ writable: false, uploadEvidence: false, manageAssignees: false })
        expect(result.blockedReason).toContain('审查活动')
      }
    })

    it('does not block on unknown parents', () => {
      expect(operations({ action: 'in_progress', finding: null, reviewCase: null })).toMatchObject({
        blockedReason: null,
        writable: true,
        manageAssignees: true,
        uploadEvidence: true,
      })
      expect(operations({ action: 'done', finding: null, reviewCase: 'in_progress' }).blockedReason).toBeNull()
    })
  })
}
