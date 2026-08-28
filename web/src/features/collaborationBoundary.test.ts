import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const genericFeatureSources = [
  new URL('./findings/FindingCreatePanel.tsx', import.meta.url),
  new URL('./findings/FindingDetailPage.tsx', import.meta.url),
  new URL('./actions/ActionItemDetailPage.tsx', import.meta.url),
]

function source(url: URL): string {
  return readFileSync(url, 'utf8')
}

describe('M3.5.3 generic collaboration boundaries', () => {
  it('keeps Scenario identity branching out of generic Finding and Action features', () => {
    for (const url of genericFeatureSources) {
      expect(source(url)).not.toContain('process_review')
    }
  })

  it('keeps HTTP transport inside the shared API module', () => {
    for (const url of genericFeatureSources) {
      expect(source(url)).not.toMatch(/\bfetch\s*\(/)
    }
  })

  it('does not leak M3.5.4 notification reminder or management commands into this slice', () => {
    for (const url of genericFeatureSources) {
      const text = source(url)
      expect(text).not.toContain('/me/notifications')
      expect(text).not.toContain('manual-nudge')
      expect(text).not.toContain('reminder')
      expect(text).not.toContain('/management')
    }
  })
})
