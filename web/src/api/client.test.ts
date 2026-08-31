import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ApiNetworkError,
  ApiTimeoutError,
  DEFAULT_API_TIMEOUT_MS,
  installSessionUnauthorizedHandler,
  publicApiRequest,
  sessionApiRequest,
} from './client'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('shared API boundary', () => {
  it('uses relative EasyAudit API paths without adding bearer credentials', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init === undefined) throw new Error('Expected request init')
      expect(init.headers instanceof Headers).toBe(true)
      expect((init.headers as Headers).has('Authorization')).toBe(false)
      expect(init.credentials).toBeUndefined()
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(sessionApiRequest<{ ok: boolean }>('/api/v1/me')).resolves.toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/me', expect.any(Object))
  })

  it('rejects non-relative API origins', async () => {
    await expect(sessionApiRequest('https://api.example.test/api/v1/me')).rejects.toThrow(
      'relative /api/v1/* paths',
    )
  })

  it('signals authenticated-session 401 centrally without retry', async () => {
    const unauthorized = vi.fn()
    const uninstall = installSessionUnauthorizedHandler(unauthorized)
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: 'Authentication required' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(sessionApiRequest('/api/v1/me')).rejects.toMatchObject({ status: 401 })
    expect(fetchMock).toHaveBeenCalledOnce()
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

    await expect(
      publicApiRequest('/api/v1/auth/login', { method: 'POST' }),
    ).rejects.toMatchObject({ status: 401 })
    expect(unauthorized).not.toHaveBeenCalled()
    uninstall()
  })

  it('applies the 15-second default timeout and never retries a mutation', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          'abort',
          () => reject(new DOMException('Aborted', 'AbortError')),
          { once: true },
        )
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const assertion = expect(
      publicApiRequest('/api/v1/auth/login', { method: 'POST', body: '{}' }),
    ).rejects.toBeInstanceOf(ApiTimeoutError)
    await vi.advanceTimersByTimeAsync(DEFAULT_API_TIMEOUT_MS)
    await assertion
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('retries a safe GET once for a transient 503 and never a third time', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response('', { status: 503 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    const request = sessionApiRequest<{ ok: boolean }>('/api/v1/me')
    await vi.advanceTimersByTimeAsync(50)
    await expect(request).resolves.toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('does not retry a GET on non-retryable 500', async () => {
    const fetchMock = vi.fn(async () => new Response('', { status: 500 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(sessionApiRequest('/api/v1/me')).rejects.toMatchObject({ status: 500 })
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('does not retry mutations after transport failure', async () => {
    const fetchMock = vi.fn(async () => {
      throw new TypeError('network down')
    })
    vi.stubGlobal('fetch', fetchMock)
    await expect(
      sessionApiRequest('/api/v1/review-plans', { method: 'POST', body: '{}' }),
    ).rejects.toBeInstanceOf(ApiNetworkError)
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('does not retry caller cancellation or misclassify it as timeout', async () => {
    const controller = new AbortController()
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          'abort',
          () => reject(new DOMException('Aborted', 'AbortError')),
          { once: true },
        )
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const request = sessionApiRequest('/api/v1/me', { signal: controller.signal })
    controller.abort()
    await expect(request).rejects.toMatchObject({ name: 'AbortError' })
    expect(fetchMock).toHaveBeenCalledOnce()
  })
})
