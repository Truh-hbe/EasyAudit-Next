import { expect, test, type Page, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'Pilot-6 Acceptance User',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
}

const EXPORT_PATH = '/api/v1/management/review-cases/export'
const XLSX_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function stubManagementPage(page: Page) {
  await page.route((url) => url.pathname === '/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...user, must_change_password: false }),
  )
  await page.route((url) => url.pathname === '/api/v1/management/review-cases', (route) =>
    fulfillJson(route, 200, {
      as_of: '2026-10-02T01:30:00Z',
      items: [],
      total: 0,
      limit: 20,
      offset: 0,
    }),
  )
}

test('管理页面导出 CSV 携带当前筛选并触发下载', async ({ page }) => {
  await stubManagementPage(page)
  const requested: URL[] = []
  await page.route((url) => url.pathname === EXPORT_PATH, (route) => {
    requested.push(new URL(route.request().url()))
    return route.fulfill({
      status: 200,
      headers: {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition':
          'attachment; filename="review-cases-20261002T0930+0800.csv"; filename*=UTF-8\'\'review-cases-20261002T0930%2B0800.csv',
        'X-Content-Type-Options': 'nosniff',
        'Cache-Control': 'no-store',
      },
      body: 'key,value\r\n',
    })
  })

  await page.goto('/management')
  await page.getByLabel('Deadline').selectOption('overdue')
  await page.getByLabel('Case lifecycle').selectOption('in_progress')

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出 CSV' }).click()
  const download = await downloadPromise

  expect(download.suggestedFilename()).toBe('review-cases-20261002T0930+0800.csv')
  expect(requested).toHaveLength(1)
  expect(requested[0]?.searchParams.get('format')).toBe('csv')
  expect(requested[0]?.searchParams.get('deadline_status')).toBe('overdue')
  expect(requested[0]?.searchParams.get('lifecycle')).toBe('in_progress')
  expect(requested[0]?.searchParams.has('limit')).toBe(false)
})

test('管理页面导出 XLSX 触发下载', async ({ page }) => {
  await stubManagementPage(page)
  await page.route((url) => url.pathname === EXPORT_PATH, (route) =>
    route.fulfill({
      status: 200,
      headers: {
        'Content-Type': XLSX_TYPE,
        'Content-Disposition': 'attachment; filename="review-cases-20261002T0930+0800.xlsx"',
      },
      body: Buffer.from('PK'),
    }),
  )

  await page.goto('/management')
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出 XLSX' }).click()
  const download = await downloadPromise

  expect(download.suggestedFilename()).toBe('review-cases-20261002T0930+0800.xlsx')
})

test('超出行数上限时显示 422 提示且不下载', async ({ page }) => {
  await stubManagementPage(page)
  await page.route((url) => url.pathname === EXPORT_PATH, (route) =>
    fulfillJson(route, 422, {
      detail: 'Export exceeds the limit of 10000 rows; narrow the filters and retry',
    }),
  )
  let downloaded = false
  page.on('download', () => {
    downloaded = true
  })

  await page.goto('/management')
  await page.getByRole('button', { name: '导出 CSV' }).click()

  await expect(page.getByRole('alert')).toHaveText(
    'Export exceeds the limit of 10000 rows; narrow the filters and retry',
  )
  await expect(page.getByRole('button', { name: '导出 CSV' })).toBeEnabled()
  expect(downloaded).toBe(false)
})
