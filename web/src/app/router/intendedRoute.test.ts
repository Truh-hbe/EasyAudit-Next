import { describe, expect, it } from 'vitest'

import { DEFAULT_AUTHENTICATED_PATH, safeIntendedPath } from './intendedRoute'

describe('safeIntendedPath', () => {
  it.each([
    ['https://evil.example/path'],
    ['//evil.example/path'],
    ['javascript:alert(1)'],
    ['/\\evil.example/path'],
    ['/login'],
    ['/me/credential-remediation'],
    ['/unknown'],
  ])('rejects non-product redirect target %s', (candidate) => {
    expect(safeIntendedPath(candidate)).toBe(DEFAULT_AUTHENTICATED_PATH)
  })

  it('preserves approved internal product paths including query and hash', () => {
    expect(safeIntendedPath('/review-cases/abc?tab=findings#f-1')).toBe(
      '/review-cases/abc?tab=findings#f-1',
    )
  })
})
