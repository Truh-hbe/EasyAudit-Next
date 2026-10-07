import { expect, test, type Page, type Route } from '@playwright/test'

const userA = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'Session User A',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
  must_change_password: false,
}
const userB = {
  ...userA,
  id: '33333333-3333-3333-3333-333333333333',
  display_name: 'Session User B',
}

const emptyWorkbench = {
  as_of: '2026-08-28T10:00:00Z',
  case_responsibilities: [],
  finding_responsibilities: [],
  action_responsibilities: [],
  verification_queue: [],
  due_soon: { cases: [], actions: [] },
  overdue: { cases: [], actions: [] },
}

const loginResponse = (user: typeof userA) => ({
  user,
  session_id: '44444444-4444-4444-4444-444444444444',
  expires_at: '2026-08-29T00:00:00Z',
})

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

// 控制一个被挂起的路由：`arrived` 在请求到达时 resolve，`release` 放行。
function gate() {
  let release!: () => void
  let arrive!: () => void
  const released = new Promise<void>((resolve) => {
    release = resolve
  })
  const arrived = new Promise<void>((resolve) => {
    arrive = resolve
  })
  return { released, arrived, release, arrive }
}

// 迟到的响应处理完成后再做"没发生"断言：等响应结束，再让页面事件循环空转两轮，
// 之后一次性检查，避免会自动重试的断言把"尚未发生"误判为通过。
async function settleAfter(page: Page, url: string, release: () => void) {
  const response = page.waitForResponse((r) => new URL(r.url()).pathname === url)
  release()
  await (await response).finished()
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        setTimeout(() => setTimeout(() => resolve(), 0), 0),
      ),
  )
}

async function login(page: Page, name: string) {
  await page.getByLabel('登录名').fill(name)
  await page.getByLabel('密码').fill('any-password-000')
  await page.getByRole('button', { name: '登录' }).click()
}

// 用与应用相同的模块实例发出一个会话请求，模拟页面里其它在途请求。
function fireSessionRequest(page: Page, path: string, { wait = true } = {}) {
  return page.evaluate(
    async ({ p, wait: awaited }) => {
      const modulePath = '/src/api/client.ts'
      const client = (await import(modulePath)) as typeof import('../../src/api/client.js')
      const pending = client.sessionApiRequest(p).catch(() => undefined)
      if (awaited) await pending
    },
    { p: path, wait },
  )
}

test('late 401 from a logged-out session does not kick the new session out', async ({ page }) => {
  let identity: typeof userA | null = userA
  const staleProbe = gate()

  await page.route('**/api/v1/me', (route) =>
    identity === null
      ? fulfillJson(route, 401, { detail: 'Authentication required' })
      : fulfillJson(route, 200, identity),
  )
  await page.route('**/api/v1/me/workbench', (route) => fulfillJson(route, 200, emptyWorkbench))
  // 不带 AbortSignal 的在途请求（例如提交中的 mutation）：退出后才返回 401
  await page.route('**/api/v1/stale-probe', async (route) => {
    staleProbe.arrive()
    await staleProbe.released
    await fulfillJson(route, 401, { detail: 'Authentication required' })
  })
  await page.route('**/api/v1/auth/logout', (route) => {
    identity = null
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/v1/auth/login', (route) => {
    identity = userB
    return fulfillJson(route, 200, loginResponse(userB))
  })

  await page.goto('/me/workbench')
  await expect(page.getByText('Session User A').first()).toBeVisible()
  await fireSessionRequest(page, '/api/v1/stale-probe', { wait: false })
  await staleProbe.arrived
  await page.getByRole('button', { name: '退出登录' }).click()
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await login(page, 'user-b')
  await expect(page.getByText('Session User B').first()).toBeVisible()

  await settleAfter(page, '/api/v1/stale-probe', staleProbe.release)

  expect(await page.getByRole('heading', { name: '登录' }).count()).toBe(0)
  expect(await page.getByText('Session User B').count()).toBeGreaterThan(0)
})

test('old /me result after the session was cleared does not restore the old identity', async ({ page }) => {
  let identity: typeof userA | null = { ...userA, must_change_password: true }
  const staleMe = gate()
  let passwordChanged = false

  await page.route('**/api/v1/me', async (route) => {
    if (passwordChanged) {
      // 修改密码后的 refresh：挂起，返回旧用户
      staleMe.arrive()
      await staleMe.released
      await fulfillJson(route, 200, userA)
      return
    }
    if (identity === null) {
      await fulfillJson(route, 401, { detail: 'Authentication required' })
    } else {
      await fulfillJson(route, 200, identity)
    }
  })
  await page.route('**/api/v1/me/password', (route) => {
    passwordChanged = true
    return fulfillJson(route, 200, userA)
  })
  await page.route('**/api/v1/me/workbench', (route) => {
    identity = null
    return fulfillJson(route, 401, { detail: 'Authentication required' })
  })

  await page.goto('/me/credential-remediation')
  await page.getByLabel('当前密码').fill('initial-password')
  await page.getByLabel('新密码', { exact: true }).fill('replacement-password')
  await page.getByLabel('确认新密码').fill('replacement-password')
  await page.getByRole('button', { name: '修改密码' }).click()
  await staleMe.arrived
  await expect(page.getByRole('heading', { name: '正在确认服务器会话' })).toBeVisible()

  // 会话在 /me 在途时被服务器判定失效（另一个请求收到 401）
  await fireSessionRequest(page, '/api/v1/me/workbench')
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()

  await settleAfter(page, '/api/v1/me', staleMe.release)

  expect(await page.getByRole('heading', { name: '登录' }).count()).toBe(1)
  expect(await page.getByText('Session User A').count()).toBe(0)
  expect(await page.getByRole('navigation', { name: '主要导航' }).count()).toBe(0)
})

test('out-of-order refresh results do not overwrite the newer session', async ({ page }) => {
  let identity: typeof userA | null = null
  let loginCount = 0
  const staleMe = gate()
  let staleMeTaken = false

  await page.route('**/api/v1/me', async (route) => {
    if (identity === userA && !staleMeTaken) {
      // 第一次登录后的 refresh：挂起，返回用户 A
      staleMeTaken = true
      staleMe.arrive()
      await staleMe.released
      await fulfillJson(route, 200, userA)
      return
    }
    if (identity === null) {
      await fulfillJson(route, 401, { detail: 'Authentication required' })
    } else {
      await fulfillJson(route, 200, identity)
    }
  })
  await page.route('**/api/v1/auth/login', (route) => {
    loginCount += 1
    identity = loginCount === 1 ? userA : userB
    return fulfillJson(route, 200, loginResponse(identity))
  })
  await page.route('**/api/v1/me/workbench', (route) => {
    if (identity === userA) {
      identity = null
      return fulfillJson(route, 401, { detail: 'Authentication required' })
    }
    return fulfillJson(route, 200, emptyWorkbench)
  })

  await page.goto('/login')
  await login(page, 'user-a')
  await staleMe.arrived

  // refresh #1 在途时会话失效，随后以用户 B 重新登录并完成 refresh #2
  await fireSessionRequest(page, '/api/v1/me/workbench')
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await login(page, 'user-b')
  await expect(page.getByText('Session User B').first()).toBeVisible()

  await settleAfter(page, '/api/v1/me', staleMe.release)

  expect(await page.getByText('Session User A').count()).toBe(0)
  expect(await page.getByText('Session User B').count()).toBeGreaterThan(0)
})
