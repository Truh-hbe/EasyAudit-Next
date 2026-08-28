import { describe, expect, it } from 'vitest'

import actionItemDetailSource from './actions/ActionItemDetailPage.tsx?raw'
import findingCreateSource from './findings/FindingCreatePanel.tsx?raw'
import findingDetailSource from './findings/FindingDetailPage.tsx?raw'

const genericFeatureSources = [findingCreateSource, findingDetailSource, actionItemDetailSource]

describe('M3.5.3 generic collaboration boundaries', () => {
  it('keeps Scenario identity branching out of generic Finding and Action features', () => {
    for (const source of genericFeatureSources) {
      expect(source).not.toContain('process_review')
    }
  })

  it('keeps HTTP transport inside the shared API module', () => {
    for (const source of genericFeatureSources) {
      expect(source).not.toMatch(/\bfetch\s*\(/)
    }
  })

  it('does not leak M3.5.4 notification reminder or management commands into this slice', () => {
    for (const source of genericFeatureSources) {
      expect(source).not.toContain('/me/notifications')
      expect(source).not.toContain('manual-nudge')
      expect(source).not.toContain('reminder')
      expect(source).not.toContain('/management')
    }
  })
})
