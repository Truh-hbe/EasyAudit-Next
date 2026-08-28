import { expect, test } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'Credential User',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
}

test('resolves the server session before choosing anonymous UI', async ({ page }) => {
  await page.route('**/api/v1/me', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 250))
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Authentication required' }),
    })
  })

  await page.goto('/review-cases')
  await expect(page.getByRole('heading', { name: '正在确认服务器会话' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '登录' })).not.toBeVisible()
  expect(new URL(page.url()).protocol).toBe('https:')

  await expect(page).toHaveURL(/\/login\?next=%2Freview-cases$/)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
})

test('login 401 stays an ordinary credential error', async ({ page }) => {
  await page.route('**/api/v1/me', (route) =>
    route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Authentication required"}' }),
  )
  await page.route('**/api/v1/auth/login', (route) =>
    route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Invalid login name or password"}' }),
  )

  await page.goto('/login')
  await page.getByLabel('登录名').fill('wrong-user')
  await page.getByLabel('密码').fill('wrong-password')
  await page.getByRole('button', { name: '登录' }).click()

  await expect(page.getByRole('alert')).toHaveText('登录名或密码无效')
  await expect(page).toHaveURL(/\/login$/)
})

test('authenticated password requirement wins over intended business route', async ({ page }) => {
  let loggedIn = false
  await page.route('**/api/v1/me', (route) =>
    route.fulfill({
      status: loggedIn ? 200 : 401,
      contentType: 'application/json',
      body: loggedIn
        ? JSON.stringify({ ...user, must_change_password: true })
        : '{"detail":"Authentication required"}',
    }),
  )
  await page.route('**/api/v1/auth/login', async (route) => {
    loggedIn = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        user,
        session_id: '33333333-3333-3333-3333-333333333333',
        expires_at: '2026-08-29T00:00:00Z',
      }),
    })
  })

  await page.goto('/review-cases/case-1')
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await page.getByLabel('登录名').fill('credential-user')
  await page.getByLabel('密码').fill('initial-password')
  await page.getByRole('button', { name: '登录' }).click()

  await expect(page).toHaveURL(/\/me\/credential-remediation\?next=%2Freview-cases%2Fcase-1$/)
  await expect(page.getByRole('heading', { name: '需要修改密码' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '主要导航' })).not.toBeVisible()
})

test('password remediation re-resolves server posture before resuming intended route', async ({ page }) => {
  let passwordChanged = false
  await page.route('**/api/v1/me/password', async (route) => {
    passwordChanged = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...user, must_change_password: false }),
    })
  })
  await page.route('**/api/v1/me', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...user,
        must_change_password: !passwordChanged,
      }),
    }),
  )

  await page.goto('/review-cases/case-1')
  await expect(page.getByRole('heading', { name: '需要修改密码' })).toBeVisible()
  await page.getByLabel('当前密码').fill('initial-password')
  await page.getByLabel('新密码', { exact: true }).fill('replacement-password')
  await page.getByLabel('确认新密码').fill('replacement-password')
  await page.getByRole('button', { name: '修改密码' }).click()

  await expect(page).toHaveURL(/\/review-cases\/case-1$/)
  await expect(page.getByRole('heading', { name: '审查活动' })).toBeVisible()
  expect(passwordChanged).toBe(true)
})

test('credential-ready shell exposes only structural navigation and honest placeholders', async ({ page }) => {
  await page.route('**/api/v1/me', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...user, must_change_password: false }),
    }),
  )

  await page.goto('/me/workbench')
  const nav = page.getByRole('navigation', { name: '主要导航' })
  await expect(nav).toBeVisible()
  await expect(nav.getByRole('link', { name: '我的工作' })).toBeVisible()
  await expect(nav.getByRole('link', { name: '审查活动' })).toBeVisible()
  await expect(nav.getByRole('link', { name: '通知' })).toBeVisible()
  await expect(nav.getByRole('link', { name: '管理视图' })).toBeVisible()
  await expect(nav.getByRole('link', { name: '管理设置' })).not.toBeVisible()
  await expect(page.getByRole('heading', { name: '我的工作' })).toBeVisible()
  await expect(page.getByText('当前仅提供产品结构入口')).toBeVisible()
})

test('system admin role only adds platform administration navigation hint', async ({ page }) => {
  await page.route('**/api/v1/me', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...user,
        platform_role: 'system_admin',
        must_change_password: false,
      }),
    }),
  )

  await page.goto('/me/workbench')
  await expect(
    page.getByRole('navigation', { name: '主要导航' }).getByRole('link', { name: '管理设置' }),
  ).toBeVisible()
})
