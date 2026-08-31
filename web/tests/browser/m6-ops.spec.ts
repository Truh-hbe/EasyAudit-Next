import { expect, test, type Page, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'M6 Ops User',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
  must_change_password: false,
}

const emptyWorkbench = {
  as_of: '2026-08-31T12:00:00Z',
  case_responsibilities: [],
  finding_responsibilities: [],
  action_responsibilities: [],
  verification_queue: [],
  due_soon: { cases: [], actions: [] },
  overdue: { cases: [], actions: [] },
}

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function readySession(page: Page) {
  await page.route('**/api/v1/me', (route) => fulfillJson(route, 200, user))
}

test('root ErrorBoundary contains an application render failure without exposing internals', async ({ page }) => {
  await page.route('**/api/v1/me', (route) => fulfillJson(route, 200, null))
  await page.goto('/me/workbench')

  await expect(page.getByRole('heading', { name: '页面暂时不可用' })).toBeVisible()
  await expect(page.getByRole('button', { name: '重新加载' })).toBeVisible()
  await expect(page.locator('body')).not.toContainText('TypeError')
  await expect(page.locator('body')).not.toContainText('stack')
})

test('route ErrorBoundary preserves shell and resets after navigation', async ({ page }) => {
  await readySession(page)
  await page.route('**/api/v1/me/workbench', (route) =>
    fulfillJson(route, 200, { ...emptyWorkbench, case_responsibilities: null }),
  )
  await page.route((url) => url.pathname === '/api/v1/review-cases', (route) =>
    fulfillJson(route, 200, { items: [], total: 0, limit: 20, offset: 0 }),
  )

  await page.goto('/me/workbench')
  await expect(page.getByRole('heading', { name: '当前页面暂时不可用' })).toBeVisible()
  const navigation = page.getByRole('navigation', { name: '主要导航' })
  await expect(navigation).toBeVisible()
  await expect(page.getByRole('banner').getByText('EasyAudit Next')).toBeVisible()

  await navigation.getByRole('link', { name: '审查活动' }).click()
  await expect(page.getByRole('heading', { name: '审查活动' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '当前页面暂时不可用' })).toHaveCount(0)
})

test('Workbench exits loading after the single safe GET retry and remains manually recoverable', async ({ page }) => {
  await readySession(page)
  let shouldFail = true
  let attempts = 0
  await page.route('**/api/v1/me/workbench', async (route) => {
    attempts += 1
    if (shouldFail) {
      await route.fulfill({ status: 503, body: '' })
      return
    }
    await fulfillJson(route, 200, emptyWorkbench)
  })

  await page.goto('/me/workbench')
  await expect(page.getByRole('alert')).toContainText('Request failed with HTTP 503')
  expect(attempts).toBe(2)
  await expect(page.getByRole('navigation', { name: '主要导航' })).toBeVisible()
  await expect(page.getByText('正在读取服务器 Workbench…')).toHaveCount(0)

  shouldFail = false
  const attemptsBeforeReload = attempts
  await page.getByRole('button', { name: '重新加载' }).click()
  await expect(page.getByText('暂无我参与的审查。')).toBeVisible()
  expect(attempts).toBe(attemptsBeforeReload + 1)
})
