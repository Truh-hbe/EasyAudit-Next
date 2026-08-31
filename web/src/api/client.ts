interface ApiErrorPayload {
  detail?: unknown
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export class ApiTimeoutError extends Error {
  constructor() {
    super('Request timed out')
    this.name = 'ApiTimeoutError'
  }
}

export class ApiNetworkError extends Error {
  constructor() {
    super('Network request failed')
    this.name = 'ApiNetworkError'
  }
}

type SessionUnauthorizedHandler = () => void

let sessionUnauthorizedHandler: SessionUnauthorizedHandler | null = null

export const DEFAULT_API_TIMEOUT_MS = 15_000
const RETRYABLE_GET_STATUSES = new Set([502, 503, 504])
const RETRY_BACKOFF_MIN_MS = 50
const RETRY_BACKOFF_JITTER_MS = 50

export function installSessionUnauthorizedHandler(
  handler: SessionUnauthorizedHandler,
): () => void {
  sessionUnauthorizedHandler = handler
  return () => {
    if (sessionUnauthorizedHandler === handler) {
      sessionUnauthorizedHandler = null
    }
  }
}

function assertApiPath(path: string): void {
  if (!path.startsWith('/api/v1/')) {
    throw new Error('EasyAudit API requests must use relative /api/v1/* paths')
  }
}

function safeDetail(payload: unknown, fallback: string): string {
  if (
    typeof payload === 'object' &&
    payload !== null &&
    'detail' in payload &&
    typeof (payload as ApiErrorPayload).detail === 'string'
  ) {
    return (payload as ApiErrorPayload).detail as string
  }
  return fallback
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const text = await response.text()
  if (text.length === 0) {
    return undefined
  }
  try {
    return JSON.parse(text) as unknown
  } catch {
    return undefined
  }
}

function methodFor(init: RequestInit): string {
  return (init.method ?? 'GET').toUpperCase()
}

function retryDelayMs(): number {
  return RETRY_BACKOFF_MIN_MS + Math.floor(Math.random() * RETRY_BACKOFF_JITTER_MS)
}

function waitForRetry(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, retryDelayMs()))
}

async function fetchWithTimeout(path: string, init: RequestInit): Promise<Response> {
  const controller = new AbortController()
  const callerSignal = init.signal
  let timedOut = false

  const abortFromCaller = () => controller.abort(callerSignal?.reason)
  if (callerSignal?.aborted) {
    abortFromCaller()
  } else {
    callerSignal?.addEventListener('abort', abortFromCaller, { once: true })
  }

  const timeoutId = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, DEFAULT_API_TIMEOUT_MS)

  try {
    return await fetch(path, { ...init, signal: controller.signal })
  } catch (error: unknown) {
    if (timedOut) {
      throw new ApiTimeoutError()
    }
    if (callerSignal?.aborted) {
      throw error
    }
    throw new ApiNetworkError()
  } finally {
    clearTimeout(timeoutId)
    callerSignal?.removeEventListener('abort', abortFromCaller)
  }
}

async function request<T>(
  path: string,
  init: RequestInit,
  signalSession401: boolean,
): Promise<T> {
  assertApiPath(path)

  const headers = new Headers(init.headers)
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const normalizedInit: RequestInit = { ...init, headers }
  const method = methodFor(normalizedInit)
  const maxAttempts = method === 'GET' ? 2 : 1

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      const response = await fetchWithTimeout(path, normalizedInit)
      if (
        method === 'GET' &&
        attempt + 1 < maxAttempts &&
        RETRYABLE_GET_STATUSES.has(response.status)
      ) {
        await waitForRetry()
        continue
      }

      const payload = await parseResponseBody(response)
      if (!response.ok) {
        if (signalSession401 && response.status === 401) {
          sessionUnauthorizedHandler?.()
        }
        throw new ApiError(
          response.status,
          safeDetail(payload, `Request failed with HTTP ${response.status}`),
        )
      }
      return payload as T
    } catch (error: unknown) {
      if (normalizedInit.signal?.aborted) {
        throw error
      }
      const transient = error instanceof ApiTimeoutError || error instanceof ApiNetworkError
      if (method === 'GET' && transient && attempt + 1 < maxAttempts) {
        await waitForRetry()
        continue
      }
      throw error
    }
  }

  throw new ApiNetworkError()
}

export function publicApiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  return request<T>(path, init, false)
}

export function sessionApiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  return request<T>(path, init, true)
}
