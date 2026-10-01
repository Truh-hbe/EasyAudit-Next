import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  installSessionUnauthorizedHandler,
  publicApiRequest,
  sessionApiDownload,
  sessionApiRequest,
} from './client'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('shared API boundary', () => {
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

    await expect(sessionApiRequest<{ ok: boolean }>('/api/v1/me')).resolves.toEqual({
      ok: true,
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/me', expect.any(Object))
  })

  it('rejects non-relative API origins', async () => {
    await expect(
      sessionApiRequest('https://api.example.test/api/v1/me'),
    ).rejects.toThrow('relative /api/v1/* paths')
  })

  it('signals authenticated-session 401 centrally', async () => {
    const unauthorized = vi.fn()
    const uninstall = installSessionUnauthorizedHandler(unauthorized)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: 'Authentication required' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(sessionApiRequest('/api/v1/me')).rejects.toMatchObject({ status: 401 })
    expect(unauthorized).toHaveBeenCalledOnce()
    uninstall()
  })

  it('does not turn login 401 into a session-expiry signal', async () => {
    const unauthorized = vi.fn()
    const uninstall = installSessionUnauthorizedHandler(unauthorized)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: 'Invalid login name or password' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(publicApiRequest('/api/v1/auth/login')).rejects.toMatchObject({
      status: 401,
    })
    expect(unauthorized).not.toHaveBeenCalled()
    uninstall()
  })

  it('captures Retry-After header on 429 response in ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: 'Too many login attempts' }), {
          status: 429,
          headers: {
            'Content-Type': 'application/json',
            'Retry-After': '900',
          },
        }),
      ),
    )

    await expect(publicApiRequest('/api/v1/auth/login')).rejects.toMatchObject({
      status: 429,
      retryAfter: 900,
    })
  })
})

describe('file downloads', () => {
  it('returns the blob with the server-chosen filename', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response('a,b', {
          status: 200,
          headers: {
            'Content-Disposition':
              'attachment; filename="review-cases-20261002T0930+0800.csv"; filename*=UTF-8\'\'review-cases-20261002T0930%2B0800.csv',
          },
        }),
      ),
    )

    const file = await sessionApiDownload('/api/v1/management/review-cases/export', 'fallback.csv')

    expect(file.filename).toBe('review-cases-20261002T0930+0800.csv')
    expect(await file.blob.text()).toBe('a,b')
  })

  it('falls back to a default filename and surfaces the server detail on errors', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    fetchMock.mockResolvedValueOnce(new Response('x', { status: 200 }))
    await expect(sessionApiDownload('/api/v1/x', 'fallback.csv')).resolves.toMatchObject({
      filename: 'fallback.csv',
    })

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'Export exceeds the limit of 2 rows' }), {
        status: 422,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    await expect(sessionApiDownload('/api/v1/x', 'fallback.csv')).rejects.toMatchObject({
      status: 422,
      detail: 'Export exceeds the limit of 2 rows',
    })
  })

  it('rejects non-relative API origins', async () => {
    await expect(sessionApiDownload('https://example.test/api/v1/x', 'f.csv')).rejects.toThrow(
      'relative /api/v1/* paths',
    )
  })
})
