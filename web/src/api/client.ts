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

type SessionUnauthorizedHandler = () => void

let sessionUnauthorizedHandler: SessionUnauthorizedHandler | null = null

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

  const response = await fetch(path, {
    ...init,
    headers,
  })
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
