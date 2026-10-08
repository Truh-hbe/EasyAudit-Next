import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import { resetAdminUserCredential, updateAdminDepartment } from '../../api/admin'
import { adminErrorMessage, scenarioVersionLabel } from './AdminPage'

describe('M5.4 administrator contracts', () => {
  it('uses exact resource IDs and explicit null clears', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'department-1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await updateAdminDepartment('department/1', {
      name: 'Updated department',
      parent_id: null,
      is_active: true,
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/admin/departments/department%2F1',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          name: 'Updated department',
          parent_id: null,
          is_active: true,
        }),
      }),
    )
    vi.unstubAllGlobals()
  })

  it('keeps the temporary password only in the reset POST body', async () => {
    const temporaryPassword = 'secret-temporary-password-000'
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'user-1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await resetAdminUserCredential('user/1', { temporary_password: temporaryPassword })

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/v1/admin/users/user%2F1/credential-reset')
    expect(path).not.toContain(temporaryPassword)
    expect(init.method).toBe('POST')
    expect(init.body).toBe(JSON.stringify({ temporary_password: temporaryPassword }))
    vi.unstubAllGlobals()
  })

  it('renders only the HTTP status for failed reads and exact scenario labels', () => {
    const secret = 'secret-that-must-not-be-rendered'
    expect(adminErrorMessage(new ApiError(500, secret), 'fallback')).toBe('请求失败（状态码 500）。')
    expect(adminErrorMessage(new Error('network down'), 'fallback')).toBe('network down')
    expect(adminErrorMessage('x', 'fallback')).toBe('fallback')
    expect(scenarioVersionLabel('process_review', 1)).toBe('process_review@1')
  })
})
