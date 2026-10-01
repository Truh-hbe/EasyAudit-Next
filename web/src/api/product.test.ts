import { afterEach, describe, expect, it, vi } from 'vitest'

import { EVIDENCE_MAX_BYTES, evidenceContentType, precheckEvidenceFile, uploadActionEvidence } from './product'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Evidence upload request', () => {
  it('sends the raw file as the body with its type and a percent-encoded name', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response('{}', { status: 201, headers: { 'Content-Type': 'application/json' } }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const file = new File(['%PDF-1.7'], '整改 报告.pdf', { type: 'application/pdf' })

    await uploadActionEvidence('action/1', file, ' 现场照片 ')

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(
      '/api/v1/action-items/action%2F1/evidence-uploads?description=%E7%8E%B0%E5%9C%BA%E7%85%A7%E7%89%87',
    )
    expect(init?.method).toBe('POST')
    expect(init?.body).toBe(file) // not FormData, not JSON
    const headers = init?.headers as Headers
    expect(headers.get('Content-Type')).toBe('application/pdf')
    expect(headers.get('X-Evidence-Filename')).toBe('%E6%95%B4%E6%94%B9%20%E6%8A%A5%E5%91%8A.pdf')
  })

  it('never sends a key, size or hash, and omits an empty description', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response('{}', { status: 201, headers: { 'Content-Type': 'application/json' } }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await uploadActionEvidence('a1', new File(['x'], 'a.txt', { type: 'text/plain' }), '  ')

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/action-items/a1/evidence-uploads')
    const headers = init?.headers as Headers
    const names = [...headers.keys()]
    expect(names.sort()).toEqual(['content-type', 'x-evidence-filename'])
  })

  it('derives the content type from the extension, not the OS-reported type', () => {
    expect(evidenceContentType(new File(['x'], 'rows.CSV', { type: 'application/vnd.ms-excel' }))).toBe('text/csv')
    expect(evidenceContentType(new File(['x'], 'photo.jpeg', { type: '' }))).toBe('image/jpeg')
    expect(evidenceContentType(new File(['x'], 'tool.exe', { type: 'application/x-msdownload' }))).toBe('application/x-msdownload')
    expect(evidenceContentType(new File(['x'], 'noextension', { type: '' }))).toBe('application/octet-stream')
  })

  it('does not retry on failure', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify({ detail: 'too big' }), {
        status: 413,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      uploadActionEvidence('a1', new File(['x'], 'a.txt', { type: 'text/plain' })),
    ).rejects.toMatchObject({ status: 413 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('pre-checks size and type locally', () => {
    const big = new File(['x'], 'big.pdf', { type: 'application/pdf' })
    Object.defineProperty(big, 'size', { value: EVIDENCE_MAX_BYTES + 1 })
    const exact = new File(['x'], 'ok.pdf', { type: 'application/pdf' })
    Object.defineProperty(exact, 'size', { value: EVIDENCE_MAX_BYTES })

    expect(precheckEvidenceFile(big)).toBe('too_large')
    expect(precheckEvidenceFile(exact)).toBeNull()
    expect(precheckEvidenceFile(new File(['x'], 'tool.exe'))).toBe('type_not_allowed')
    expect(precheckEvidenceFile(new File(['x'], 'noextension'))).toBe('type_not_allowed')
    expect(precheckEvidenceFile(new File(['x'], 'ROWS.CSV'))).toBeNull()
  })
})
