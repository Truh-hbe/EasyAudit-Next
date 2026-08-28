import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiRequest } from './client'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('apiRequest', () => {
  it('uses relative EasyAudit API paths without adding bearer credentials', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init === undefined) {
        throw new Error('Expected request init')
      }
      expect(init.headers instanceof Headers).toBe(true)
      expect((init.headers as Headers).has('Authorization')).toBe(false)
      expect(init.credentials).toBeUndefined()
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(apiRequest<{ ok: boolean }>('/api/v1/me')).resolves.toEqual({
      ok: true,
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/me', expect.any(Object))
  })

  it('rejects non-relative API origins', async () => {
    await expect(
      apiRequest('https://api.example.test/api/v1/me'),
    ).rejects.toThrow('relative /api/v1/* paths')
  })

  it('preserves HTTP status and safe FastAPI detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: 'Authentication required' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(apiRequest('/api/v1/me')).rejects.toMatchObject({
      status: 401,
      detail: 'Authentication required',
    })
  })
})
