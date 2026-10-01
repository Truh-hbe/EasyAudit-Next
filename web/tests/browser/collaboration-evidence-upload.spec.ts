import { expect, test, type Page, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'Evidence User',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
}
const SHA = 'c0ffee1234567890'.repeat(4)
const UPLOAD_PATH = '/api/v1/action-items/action-1/evidence-uploads'

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

function evidenceResponse(name: string, size: number) {
  return {
    id: 'evidence-1',
    organization_id: user.organization_id,
    action_item_id: 'action-1',
    storage_key: `org/${user.organization_id}/evidence/private-key`,
    original_name: name,
    content_type: 'application/pdf',
    size_bytes: size,
    sha256: SHA,
    description: '现场记录',
    uploaded_by: user.id,
    created_at: '2026-10-01T03:00:00Z',
  }
}

async function stubActionPage(page: Page, evidences: () => unknown[], lifecycle = 'in_progress') {
  await page.route((url) => url.pathname === '/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...user, must_change_password: false }),
  )
  await page.route((url) => url.pathname === '/api/v1/action-items/action-1', (route) =>
    fulfillJson(route, 200, {
      id: 'action-1',
      organization_id: user.organization_id,
      finding_id: 'finding-1',
      title: 'Restore calibration record',
      lifecycle,
      due_at: null,
      completed_at: null,
    }),
  )
  await page.route((url) => url.pathname === '/api/v1/findings/finding-1', (route) =>
    fulfillJson(route, 200, {
      id: 'finding-1',
      organization_id: user.organization_id,
      case_id: 'case-1',
      title: 'Calibration evidence gap',
      description: null,
      severity: 'high',
      lifecycle: 'rectifying',
      scenario_data: { issue_type: 'control_gap', project_category: 'assembly' },
      raised_by: user.id,
      raised_at: '2026-10-01T01:00:00Z',
    }),
  )
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-1', (route) =>
    fulfillJson(route, 200, {
      id: 'case-1',
      organization_id: user.organization_id,
      plan_id: null,
      scenario_key: 'process_review',
      scenario_version: 1,
      title: 'Evidence Case',
      lifecycle: 'in_progress',
      planned_start_at: null,
      planned_end_at: null,
      started_at: '2026-10-01T00:00:00Z',
      fieldwork_completed_at: null,
      closed_at: null,
      scenario_data: { area_code: 'A-01', review_type: 'routine' },
      created_by: user.id,
      created_at: '2026-10-01T00:00:00Z',
    }),
  )
  for (const child of ['assignee-views', 'activities']) {
    await page.route((url) => url.pathname === `/api/v1/action-items/action-1/${child}`, (route) =>
      fulfillJson(route, 200, []),
    )
  }
  await page.route((url) => url.pathname === '/api/v1/action-items/action-1/evidences', (route) =>
    fulfillJson(route, 200, evidences()),
  )
}

test('uploading a file sends the raw bytes and shows the server-confirmed metadata', async ({ page }) => {
  const stored: unknown[] = []
  const uploads: { contentType: string | undefined; filename: string | undefined; body: Buffer | null; search: string }[] = []
  await stubActionPage(page, () => stored)
  await page.route((url) => url.pathname === UPLOAD_PATH, (route) => {
    const request = route.request()
    uploads.push({
      contentType: request.headers()['content-type'],
      filename: request.headers()['x-evidence-filename'],
      body: request.postDataBuffer(),
      search: new URL(request.url()).search,
    })
    const evidence = evidenceResponse('整改报告.pdf', 9)
    stored.push(evidence)
    return fulfillJson(route, 201, evidence)
  })

  await page.goto('/action-items/action-1')
  await expect(page.getByText('暂无 Evidence metadata。')).toBeVisible()
  await page.getByLabel('证据文件').setInputFiles({
    name: '整改报告.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.7\n'),
  })
  await page.getByLabel('说明（可选）').fill('现场记录')
  await page.getByRole('button', { name: '上传证据' }).click()

  await expect(page.getByRole('status')).toContainText('服务器已确认上传：整改报告.pdf')
  await expect(page.getByRole('status')).toContainText('9 B')
  await expect(page.getByRole('status')).toContainText(`SHA-256 ${SHA.slice(0, 12)}`)
  await expect(page.getByRole('status')).not.toContainText(SHA)
  await expect(page.getByRole('listitem').filter({ hasText: '整改报告.pdf' })).toBeVisible() // refreshed list
  await expect(page.getByText('暂无 Evidence metadata。')).toHaveCount(0)
  await expect(page.getByText('private-key')).toHaveCount(0)

  expect(uploads).toHaveLength(1)
  expect(uploads[0].contentType).toBe('application/pdf')
  expect(decodeURIComponent(uploads[0].filename ?? '')).toBe('整改报告.pdf')
  expect(uploads[0].body?.toString()).toBe('%PDF-1.7\n') // raw bytes, not multipart
  expect(uploads[0].search).toBe(`?description=${encodeURIComponent('现场记录')}`)
})

const failures = [
  { status: 413, detail: 'Evidence exceeds the maximum size of 26214400 bytes', text: '文件超过大小上限，未上传。' },
  { status: 415, detail: 'Content type is not allowed for Evidence', text: '文件类型不被允许，或扩展名与类型不一致。' },
  { status: 409, detail: 'Concurrent Finding transition', text: '数据已过期，已刷新。' },
  { status: 422, detail: 'Evidence cannot be registered for a cancelled ActionItem', text: '无法登记证据：Evidence cannot be registered for a cancelled ActionItem' },
]

for (const failure of failures) {
  test(`upload failure ${failure.status} is shown once and never retried automatically`, async ({ page }) => {
    let attempts = 0
    await stubActionPage(page, () => [])
    await page.route((url) => url.pathname === UPLOAD_PATH, (route) => {
      attempts += 1
      return fulfillJson(route, failure.status, { detail: failure.detail })
    })

    await page.goto('/action-items/action-1')
    await page.getByLabel('证据文件').setInputFiles({
      name: 'scan.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('data'),
    })
    await page.getByRole('button', { name: '上传证据' }).click()

    await expect(page.getByRole('alert')).toContainText(failure.text)
    await page.waitForTimeout(500)
    expect(attempts).toBe(1)
    await expect(page.getByRole('button', { name: '上传证据' })).toBeEnabled() // user decides to retry
  })
}

test('files over the limit or of a disallowed type are refused locally without a request', async ({ page }) => {
  let attempts = 0
  await stubActionPage(page, () => [])
  await page.route((url) => url.pathname === UPLOAD_PATH, (route) => {
    attempts += 1
    return fulfillJson(route, 201, evidenceResponse('x.pdf', 1))
  })

  await page.goto('/action-items/action-1')
  await page.getByLabel('证据文件').setInputFiles({
    name: 'huge.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.alloc(25 * 1024 * 1024 + 1),
  })
  await page.getByRole('button', { name: '上传证据' }).click()
  await expect(page.getByRole('alert')).toContainText('文件超过大小上限，未上传。')

  await page.getByLabel('证据文件').setInputFiles({
    name: 'tool.exe',
    mimeType: 'application/x-msdownload',
    buffer: Buffer.from('MZ'),
  })
  await page.getByRole('button', { name: '上传证据' }).click()
  await expect(page.getByRole('alert')).toContainText('文件类型不被允许')
  expect(attempts).toBe(0)
})

test('a dropped connection is reported as unconfirmed and not retried', async ({ page }) => {
  let attempts = 0
  await stubActionPage(page, () => [])
  await page.route((url) => url.pathname === UPLOAD_PATH, (route) => {
    attempts += 1
    return route.abort('connectionreset')
  })

  await page.goto('/action-items/action-1')
  await page.getByLabel('证据文件').setInputFiles({
    name: 'scan.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('data'),
  })
  await page.getByRole('button', { name: '上传证据' }).click()

  await expect(page.getByRole('alert')).toContainText('上传中断，服务器未确认')
  await page.waitForTimeout(500)
  expect(attempts).toBe(1)
})

test('a cancelled Action offers no upload form', async ({ page }) => {
  await stubActionPage(page, () => [], 'cancelled')

  await page.goto('/action-items/action-1')

  await expect(page.getByText('当前 Action 已取消，不能上传证据。')).toBeVisible()
  await expect(page.getByLabel('证据文件')).toHaveCount(0)
})
