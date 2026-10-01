interface ApiErrorPayload {
  detail?: unknown
}

function parseRetryAfter(
  source?: number | Headers | { get(name: string): string | null } | null,
): number | null {
  if (typeof source === 'number' && Number.isFinite(source) && source > 0) {
    return source
  }
  if (source !== null && typeof source === 'object' && typeof source.get === 'function') {
    const raw = source.get('Retry-After')
    if (raw !== null && raw !== undefined && raw.trim() !== '') {
      const parsed = Number(raw)
      if (Number.isFinite(parsed) && parsed > 0) {
        return parsed
      }
    }
  }
  return null
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  readonly retryAfter: number | null

  constructor(
    status: number,
    detail: string,
    retryAfter?: number | Headers | { get(name: string): string | null } | null,
  ) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.retryAfter = parseRetryAfter(retryAfter)
  }
}

export function isIdempotencyKeyReuse(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 409 &&
    error.detail === 'Idempotency-Key reused with a different request'
  )
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
      response.headers,
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

export interface DownloadedFile {
  blob: Blob
  filename: string
}

function filenameFromDisposition(header: string | null): string | null {
  if (header === null) return null
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (encoded?.[1] !== undefined) {
    try {
      return decodeURIComponent(encoded[1])
    } catch {
      // fall through to the plain filename
    }
  }
  const plain = /filename="([^"]+)"/i.exec(header)
  return plain?.[1] ?? null
}

export async function sessionApiDownload(
  path: string,
  fallbackFilename: string,
  init: RequestInit = {},
): Promise<DownloadedFile> {
  assertApiPath(path)
  const response = await fetch(path, init)
  if (!response.ok) {
    if (response.status === 401) {
      sessionUnauthorizedHandler?.()
    }
    throw new ApiError(
      response.status,
      safeDetail(await parseResponseBody(response), `Request failed with HTTP ${response.status}`),
      response.headers,
    )
  }
  return {
    blob: await response.blob(),
    filename: filenameFromDisposition(response.headers.get('Content-Disposition')) ?? fallbackFilename,
  }
}
