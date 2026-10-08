import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import { resolveServerSession, resolutionErrorMessage } from './session'

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

describe('resolutionErrorMessage', () => {
  it('maps failures to fixed Chinese text without backend detail', () => {
    expect(resolutionErrorMessage(new ApiError(503, 'unavailable'))).toBe('服务器暂不可用，请稍后重试。')
    expect(resolutionErrorMessage(new ApiError(500, 'boom'))).toBe('无法确认登录状态（状态码 500），请重试。')
    expect(resolutionErrorMessage(new TypeError('Failed to fetch'))).toBe('无法连接到服务器，请检查网络后重试。')
  })
})
