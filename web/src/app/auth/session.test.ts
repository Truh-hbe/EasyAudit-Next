import { afterEach, describe, expect, it, vi } from 'vitest'

import { resolveServerSession } from './session'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('resolveServerSession', () => {
  it('maps GET /me 401 to anonymous', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: 'Authentication required' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(resolveServerSession()).resolves.toEqual({ status: 'anonymous' })
  })

  it('keeps credential posture attached to authenticated server identity', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            id: '11111111-1111-1111-1111-111111111111',
            organization_id: '22222222-2222-2222-2222-222222222222',
            display_name: 'Credential User',
            platform_role: 'ordinary_user',
            primary_department_id: null,
            is_active: true,
            must_change_password: true,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    await expect(resolveServerSession()).resolves.toMatchObject({
      status: 'authenticated',
      user: { must_change_password: true },
    })
  })
})
