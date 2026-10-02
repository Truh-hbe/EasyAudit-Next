import { expect, test, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'Chunk User',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
  must_change_password: false,
}

function fulfillJson(route: Route, body: unknown) {
  return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
}

const emptyWorkbench = {
  as_of: '2026-08-28T10:00:00Z',
  case_responsibilities: [],
  finding_responsibilities: [],
  action_responsibilities: [],
  verification_queue: [],
  overdue: { cases: [], actions: [] },
  due_soon: { cases: [], actions: [] },
}

const emptyNotifications = { items: [], unread_count: 0, limit: 20, offset: 0 }

const notificationChunk = (url: URL) =>
  /NotificationCenterPage/.test(url.pathname)

test('chunk load failure shows a reload prompt instead of a blank page, and reload recovers', async ({ page }) => {
  await page.route((url) => url.pathname === '/api/v1/me', (route) => fulfillJson(route, user))
  await page.route((url) => url.pathname === '/api/v1/me/workbench', (route) => fulfillJson(route, emptyWorkbench))
  await page.route(
    (url) => url.pathname === '/api/v1/me/notifications',
    (route) => fulfillJson(route, emptyNotifications),
  )

  let chunkRequests = 0
  await page.route(notificationChunk, (route) => {
    chunkRequests += 1
    return route.abort('failed')
  })

  await page.goto('/me/workbench')
  await expect(page.getByRole('heading', { name: '我的工作' })).toBeVisible()

  await page.getByRole('navigation', { name: '主要导航' }).getByRole('link', { name: '通知' }).click()

  const alert = page.getByRole('alert').filter({ hasText: '页面加载失败' })
  await expect(alert).toBeVisible()
  // 外壳与导航保持可用，不白屏；不自动重试。
  await expect(page.getByRole('navigation', { name: '主要导航' })).toBeVisible()
  const requestsAtFailure = chunkRequests
  await page.waitForTimeout(500)
  expect(chunkRequests).toBe(requestsAtFailure)

  // 资源恢复后点击“重新加载页面”，整页重载并进入目标页。
  await page.unroute(notificationChunk)
  await alert.getByRole('button', { name: '重新加载页面' }).click()
  await expect(page.getByRole('heading', { name: '通知' })).toBeVisible()
  await expect(page).toHaveURL(/\/me\/notifications$/)
})

test('deep link to a lazy route with a failing chunk keeps the shell and the URL', async ({ page }) => {
  await page.route((url) => url.pathname === '/api/v1/me', (route) => fulfillJson(route, user))
  await page.route(notificationChunk, (route) => route.abort('failed'))

  await page.goto('/me/notifications')
  await expect(page.getByRole('alert').filter({ hasText: '页面加载失败' })).toBeVisible()
  await expect(page.getByRole('button', { name: '重新加载页面' })).toBeVisible()
  await expect(page).toHaveURL(/\/me\/notifications$/)
})

test('navigating away from a failed chunk recovers; revisiting it fails again without retrying', async ({ page }) => {
  await page.route((url) => url.pathname === '/api/v1/me', (route) => fulfillJson(route, user))
  await page.route((url) => url.pathname === '/api/v1/me/workbench', (route) => fulfillJson(route, emptyWorkbench))
  let chunkRequests = 0
  await page.route(notificationChunk, (route) => {
    chunkRequests += 1
    return route.abort('failed')
  })
  const nav = page.getByRole('navigation', { name: '主要导航' })
  const failure = page.getByRole('alert').filter({ hasText: '页面加载失败' })

  await page.goto('/me/workbench')
  await expect(page.getByRole('heading', { name: '我的工作' })).toBeVisible()
  await nav.getByRole('link', { name: '通知' }).click()
  await expect(failure).toBeVisible()
  const failedRequests = chunkRequests

  // 点导航回到正常页。
  await nav.getByRole('link', { name: '我的工作' }).click()
  await expect(page).toHaveURL(/\/me\/workbench$/)
  await expect(page.getByRole('heading', { name: '我的工作' })).toBeVisible()
  await expect(failure).toHaveCount(0)

  // 回到失败路由：仍提示失败，且不重试 chunk 请求。
  await nav.getByRole('link', { name: '通知' }).click()
  await expect(failure).toBeVisible()
  await page.waitForTimeout(300)
  expect(chunkRequests).toBe(failedRequests)

  // 浏览器后退回到上一页。
  await page.goBack()
  await expect(page).toHaveURL(/\/me\/workbench$/)
  await expect(page.getByRole('heading', { name: '我的工作' })).toBeVisible()
  await expect(failure).toHaveCount(0)
})
