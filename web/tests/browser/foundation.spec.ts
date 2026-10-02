import { expect, test, type Page, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'Credential User',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
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

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

function createDeferred() {
  let resolve!: () => void
  const promise = new Promise<void>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

async function stubReadySession(page: Page, platformRole = 'ordinary_user') {
  await page.route('**/api/v1/me', (route) =>
    fulfillJson(route, 200, {
      ...user,
      platform_role: platformRole,
      must_change_password: false,
    }),
  )
}

async function stubEmptyWorkbench(page: Page) {
  await page.route('**/api/v1/me/workbench', (route) => fulfillJson(route, 200, emptyWorkbench))
}

function caseResponse(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    organization_id: user.organization_id,
    plan_id: null,
    scenario_key: 'process_review',
    scenario_version: 1,
    title: 'Foundation Case',
    lifecycle: 'in_progress',
    planned_start_at: '2026-08-20T00:00:00Z',
    planned_end_at: '2026-08-30T00:00:00Z',
    started_at: '2026-08-21T00:00:00Z',
    fieldwork_completed_at: null,
    closed_at: null,
    scenario_data: { area_code: 'A-01', review_type: 'routine' },
    created_by: user.id,
    created_at: '2026-08-18T00:00:00Z',
    ...overrides,
  }
}

async function stubCaseSections(page: Page, caseId: string) {
  await page.route(`**/api/v1/review-cases/${caseId}/members`, (route) => fulfillJson(route, 200, []))
  await page.route(`**/api/v1/review-cases/${caseId}/findings`, (route) => fulfillJson(route, 200, []))
  await page.route(`**/api/v1/review-cases/${caseId}/activities`, (route) => fulfillJson(route, 200, []))
  await page.route(`**/api/v1/management/review-cases/${caseId}/progress`, (route) => fulfillJson(route, 404, { detail: 'Not found' }))
}

test('resolves the server session before choosing anonymous UI', async ({ page }) => {
  const sessionGate = createDeferred()
  await page.route('**/api/v1/me', async (route) => {
    await sessionGate.promise
    await fulfillJson(route, 401, { detail: 'Authentication required' })
  })

  await page.goto('/review-cases')
  await expect(page.getByRole('heading', { name: '正在确认服务器会话' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '登录' })).not.toBeVisible()
  expect(new URL(page.url()).protocol).toBe('https:')

  sessionGate.resolve()

  await expect(page).toHaveURL(/\/login\?next=%2Freview-cases$/)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
})

test('login 401 stays an ordinary credential error', async ({ page }) => {
  await page.route('**/api/v1/me', (route) =>
    fulfillJson(route, 401, { detail: 'Authentication required' }),
  )
  await page.route('**/api/v1/auth/login', (route) =>
    fulfillJson(route, 401, { detail: 'Invalid login name or password' }),
  )

  await page.goto('/login')
  await page.getByLabel('登录名').fill('wrong-user')
  await page.getByLabel('密码').fill('wrong-password')
  await page.getByRole('button', { name: '登录' }).click()

  await expect(page.getByRole('alert')).toHaveText('登录名或密码无效')
  await expect(page).toHaveURL(/\/login$/)
})

test('login 429 displays explicit rate limit message and does not auto retry', async ({ page }) => {
  let loginAttempts = 0
  await page.route('**/api/v1/me', (route) =>
    fulfillJson(route, 401, { detail: 'Authentication required' }),
  )
  await page.route('**/api/v1/auth/login', async (route) => {
    loginAttempts += 1
    await route.fulfill({
      status: 429,
      contentType: 'application/json',
      headers: { 'Retry-After': '900' },
      body: JSON.stringify({ detail: 'Too many login attempts' }),
    })
  })

  await page.goto('/login')
  await page.getByLabel('登录名').fill('throttled-user')
  await page.getByLabel('密码').fill('some-password')
  await page.getByRole('button', { name: '登录' }).click()

  await expect(page.getByRole('alert')).toHaveText('登录尝试过于频繁，请约 15 分钟后再试。')
  await expect(page).toHaveURL(/\/login$/)

  await page.waitForTimeout(500)
  expect(loginAttempts).toBe(1)
})

test('authenticated password requirement wins over intended business route', async ({ page }) => {
  let loggedIn = false
  await page.route('**/api/v1/me', (route) =>
    fulfillJson(
      route,
      loggedIn ? 200 : 401,
      loggedIn ? { ...user, must_change_password: true } : { detail: 'Authentication required' },
    ),
  )
  await page.route('**/api/v1/auth/login', async (route) => {
    loggedIn = true
    await fulfillJson(route, 200, {
      user,
      session_id: '33333333-3333-3333-3333-333333333333',
      expires_at: '2026-08-29T00:00:00Z',
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

test('password remediation re-resolves server posture before resuming intended Case route', async ({ page }) => {
  let passwordChanged = false
  await page.route('**/api/v1/me/password', async (route) => {
    passwordChanged = true
    await fulfillJson(route, 200, { ...user, must_change_password: false })
  })
  await page.route('**/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...user, must_change_password: !passwordChanged }),
  )
  await page.route('**/api/v1/review-cases/case-1', (route) => fulfillJson(route, 200, caseResponse('case-1')))
  await stubCaseSections(page, 'case-1')

  await page.goto('/review-cases/case-1')
  await expect(page.getByRole('heading', { name: '需要修改密码' })).toBeVisible()
  await page.getByLabel('当前密码').fill('initial-password')
  await page.getByLabel('新密码', { exact: true }).fill('replacement-password')
  await page.getByLabel('确认新密码').fill('replacement-password')
  await page.getByRole('button', { name: '修改密码' }).click()

  await expect(page).toHaveURL(/\/review-cases\/case-1$/)
  await expect(page.getByRole('heading', { name: 'Foundation Case' })).toBeVisible()
  expect(passwordChanged).toBe(true)
})

test('credential-ready shell renders the real empty Workbench while preserving navigation hints', async ({ page }) => {
  await stubReadySession(page)
  await stubEmptyWorkbench(page)

  await page.goto('/me/workbench')
  const nav = page.getByRole('navigation', { name: '主要导航' })
  await expect(nav).toBeVisible()
  await expect(nav.getByRole('link', { name: '我的工作' })).toBeVisible()
  await expect(nav.getByRole('link', { name: '审查活动' })).toBeVisible()
  await expect(nav.getByRole('link', { name: '通知' })).toBeVisible()
  await expect(nav.getByRole('link', { name: '管理视图' })).toBeVisible()
  await expect(nav.getByRole('link', { name: '管理设置' })).not.toBeVisible()
  await expect(page.getByRole('heading', { name: '我的工作' })).toBeVisible()
  await expect(page.getByText('暂无我参与的审查。')).toBeVisible()
})

test('system admin role only adds platform administration navigation hint', async ({ page }) => {
  await stubReadySession(page, 'system_admin')
  await stubEmptyWorkbench(page)

  await page.goto('/me/workbench')
  await expect(
    page.getByRole('navigation', { name: '主要导航' }).getByRole('link', { name: '管理设置' }),
  ).toBeVisible()
  await expect(page.getByText('暂无我参与的审查。')).toBeVisible()
})

test('Workbench renders only server-projected categories and links to original resources', async ({ page }) => {
  const requestedPaths: string[] = []
  page.on('request', (request) => requestedPaths.push(new URL(request.url()).pathname))
  await stubReadySession(page)
  await page.route('**/api/v1/me/workbench', (route) =>
    fulfillJson(route, 200, {
      as_of: '2026-08-28T10:00:00Z',
      case_responsibilities: [
        { id: 'case-a', title: 'Server Case A', lifecycle: 'in_progress', role_keys: ['observer'], planned_end_at: null },
      ],
      finding_responsibilities: [
        { id: 'finding-a', case_id: 'case-a', title: 'Server Finding A', severity: 'high', lifecycle: 'open', relationships: [], raised_at: '2026-08-27T00:00:00Z' },
      ],
      action_responsibilities: [
        { id: 'action-a', finding_id: 'finding-a', case_id: 'case-a', title: 'Server Action A', lifecycle: 'todo', due_at: null, relationships: [] },
      ],
      verification_queue: [
        { id: 'finding-v', case_id: 'case-a', title: 'Server Verification V', severity: 'medium', raised_at: '2026-08-26T00:00:00Z' },
      ],
      overdue: {
        cases: [{ id: 'case-overdue', title: 'Server Overdue Case', lifecycle: 'in_progress', deadline: '2026-08-20T00:00:00Z' }],
        actions: [],
      },
      due_soon: {
        cases: [],
        actions: [{ id: 'action-soon', finding_id: 'finding-a', case_id: 'case-a', title: 'Server Due Soon Action', lifecycle: 'todo', deadline: '2026-08-30T00:00:00Z' }],
      },
    }),
  )

  await page.goto('/me/workbench')
  await expect(page.getByText('Server Case A')).toBeVisible()
  await expect(page.getByText('Server Finding A')).toBeVisible()
  await expect(page.getByText('Server Action A')).toBeVisible()
  await expect(page.getByText('Server Verification V')).toBeVisible()
  await expect(page.getByText('Server Overdue Case')).toBeVisible()
  await expect(page.getByText('Server Due Soon Action')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Server Case A' })).toHaveAttribute('href', '/review-cases/case-a')
  await expect(page.getByRole('link', { name: 'Server Finding A' })).toHaveAttribute('href', '/findings/finding-a')
  await expect(page.getByRole('link', { name: 'Server Action A' })).toHaveAttribute('href', '/action-items/action-a')
  expect(requestedPaths.filter((path) => path === '/api/v1/review-cases')).toEqual([])
})

test('ReviewCase collection uses the server envelope for pagination and never renders hidden candidates', async ({ page }) => {
  await stubReadySession(page)
  const firstPageGate = createDeferred()
  await page.route((url) => url.pathname === '/api/v1/review-cases', async (route) => {
    await firstPageGate.promise
    const url = new URL(route.request().url())
    const offset = Number(url.searchParams.get('offset') ?? '0')
    const items = offset === 0
      ? [caseResponse('case-a', { title: 'Visible A' }), caseResponse('case-b', { title: 'Visible B' })]
      : [caseResponse('case-c', { title: 'Visible C' })]
    await fulfillJson(route, 200, { items, total: 3, limit: 2, offset })
  })

  await page.goto('/review-cases?limit=2&offset=0')
  await expect(page.getByText('正在读取服务器授权后的 ReviewCase 页面…')).toBeVisible()
  firstPageGate.resolve()
  await expect(page.getByText('Visible A')).toBeVisible()
  await expect(page.getByText('Visible B')).toBeVisible()
  await expect(page.getByText('Hidden H1')).toHaveCount(0)
  await expect(page.getByText('1–2 / 3')).toBeVisible()

  await page.getByRole('button', { name: '下一页' }).click()
  await expect(page).toHaveURL(/limit=2&offset=2/)
  await expect(page.getByText('Visible C')).toBeVisible()
  await expect(page.getByText('Visible A')).toHaveCount(0)
  await expect(page.getByText('3–3 / 3')).toBeVisible()
})

test('ReviewCase primary authorization failure prevents all subordinate reads and stale detail rendering', async ({ page }) => {
  await stubReadySession(page)
  let subordinateRequests = 0
  const caseGate = createDeferred()
  await page.route('**/api/v1/review-cases/blocked/**', async (route) => {
    subordinateRequests += 1
    await fulfillJson(route, 500, { detail: 'must not be called' })
  })
  await page.route('**/api/v1/management/review-cases/blocked/progress', async (route) => {
    subordinateRequests += 1
    await fulfillJson(route, 500, { detail: 'must not be called' })
  })
  await page.route('**/api/v1/review-cases/blocked', async (route) => {
    await caseGate.promise
    await fulfillJson(route, 404, { detail: 'ReviewCase not found' })
  })

  await page.goto('/review-cases/blocked')
  await expect(page.getByText('正在确认当前 ReviewCase 授权…')).toBeVisible()
  caseGate.resolve()
  await expect(page.getByRole('heading', { name: 'ReviewCase 不可用' })).toBeVisible()
  await expect(page.getByText('Foundation Case')).toHaveCount(0)
  expect(subordinateRequests).toBe(0)
})

test('ReviewCase route change binds rendered and subordinate state to the newly authorized Case', async ({ page }) => {
  await stubReadySession(page)
  let blockedSubordinateRequests = 0

  await page.route('**/api/v1/review-cases/case-a', (route) =>
    fulfillJson(route, 200, caseResponse('case-a', { title: 'Authorized Case A' })),
  )
  await page.route('**/api/v1/review-cases/case-a/members', (route) =>
    fulfillJson(route, 200, [
      {
        case_id: 'case-a',
        user_id: 'member-a',
        role_key: 'observer',
        joined_at: '2026-08-18T00:00:00Z',
        display_name: 'Case A Member',
      },
    ]),
  )
  await page.route('**/api/v1/review-cases/case-a/findings', (route) => fulfillJson(route, 200, []))
  await page.route('**/api/v1/review-cases/case-a/activities', (route) => fulfillJson(route, 200, []))
  await page.route('**/api/v1/management/review-cases/case-a/progress', (route) =>
    fulfillJson(route, 404, { detail: 'Not found' }),
  )

  await page.route('**/api/v1/review-cases/case-b/**', async (route) => {
    blockedSubordinateRequests += 1
    await fulfillJson(route, 500, { detail: 'must not be called' })
  })
  await page.route('**/api/v1/management/review-cases/case-b/progress', async (route) => {
    blockedSubordinateRequests += 1
    await fulfillJson(route, 500, { detail: 'must not be called' })
  })
  const caseBGate = createDeferred()
  await page.route('**/api/v1/review-cases/case-b', async (route) => {
    await caseBGate.promise
    await fulfillJson(route, 404, { detail: 'ReviewCase not found' })
  })

  await page.goto('/review-cases/case-a')
  await expect(page.getByRole('heading', { name: 'Authorized Case A' })).toBeVisible()
  await expect(page.getByText('Case A Member')).toBeVisible()

  await page.evaluate(`
    history.pushState({}, '', '/review-cases/case-b')
    dispatchEvent(new PopStateEvent('popstate'))
  `)

  await expect(page).toHaveURL(/\/review-cases\/case-b$/)
  await expect(page.getByText('正在确认当前 ReviewCase 授权…')).toBeVisible()
  await expect(page.getByText('Authorized Case A')).toHaveCount(0)
  await expect(page.getByText('Case A Member')).toHaveCount(0)
  caseBGate.resolve()
  await expect(page.getByRole('heading', { name: 'ReviewCase 不可用' })).toBeVisible()
  expect(blockedSubordinateRequests).toBe(0)
})

test('visible Case keeps generic truth when exact Scenario UI is unsupported and management progress is unavailable', async ({ page }) => {
  await stubReadySession(page)
  await page.route('**/api/v1/review-cases/case-99', (route) =>
    fulfillJson(route, 200, caseResponse('case-99', {
      title: 'Unknown Version Case',
      scenario_version: 99,
      scenario_data: { area_code: 'SHOULD-NOT-FALLBACK', review_type: 'secret' },
    })),
  )
  await stubCaseSections(page, 'case-99')

  await page.goto('/review-cases/case-99')
  await expect(page.getByRole('heading', { name: 'Unknown Version Case' })).toBeVisible()
  await expect(page.getByText('不支持当前精确 Scenario UI：process_review@99。通用 Case 信息仍可查看。')).toBeVisible()
  await expect(page.getByText('SHOULD-NOT-FALLBACK')).toHaveCount(0)
  await expect(page.getByText('当前用户没有可用的管理进度摘要。')).toBeVisible()
})

test('visible process_review@1 Case renders Case-scoped identity, Findings, server progress and metadata-free Activity', async ({ page }) => {
  await stubReadySession(page)
  await page.route('**/api/v1/review-cases/case-real', (route) => fulfillJson(route, 200, caseResponse('case-real', { title: 'Visible Product Case' })))
  await page.route('**/api/v1/review-cases/case-real/members', (route) => fulfillJson(route, 200, [
    { case_id: 'case-real', user_id: 'member-1', role_key: 'lead', joined_at: '2026-08-18T00:00:00Z', display_name: 'Human Member' },
  ]))
  await page.route('**/api/v1/review-cases/case-real/findings', (route) => fulfillJson(route, 200, [
    { id: 'finding-real', organization_id: user.organization_id, case_id: 'case-real', title: 'Visible Finding', description: null, severity: 'high', lifecycle: 'rectifying', scenario_data: {}, raised_by: user.id, raised_at: '2026-08-22T00:00:00Z' },
  ]))
  await page.route('**/api/v1/review-cases/case-real/activities', (route) => fulfillJson(route, 200, [
    { id: 'activity-1', subject_type: 'review_case', subject_id: 'case-real', event_type: 'review_case.created', actor_id: user.id, occurred_at: '2026-08-18T00:00:00Z' },
  ]))
  await page.route('**/api/v1/management/review-cases/case-real/progress', (route) => fulfillJson(route, 200, {
    as_of: '2026-08-28T10:00:00Z',
    case: {
      id: 'case-real', review_plan_id: null, title: 'Visible Product Case', scenario_key: 'process_review', scenario_version: 1,
      lifecycle: 'in_progress', planned_start_at: null, planned_end_at: null, deadline_bucket: 'none',
      findings: { total: 1, open: 0, rectifying: 1, verifying: 0, closed: 0, voided: 0 },
      actions: { total: 1, todo: 1, in_progress: 0, done: 0, cancelled: 0, overdue: 1, due_soon: 0 },
    },
    findings: [], overdue_actions: [], due_soon_actions: [],
  }))

  await page.goto('/review-cases/case-real')
  await expect(page.getByRole('heading', { name: 'Visible Product Case' })).toBeVisible()
  await expect(page.getByText('A-01')).toBeVisible()
  await expect(page.getByText('Human Member')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Visible Finding' })).toHaveAttribute('href', '/findings/finding-real')
  await expect(page.getByText('review_case.created')).toBeVisible()
  await expect(page.getByText('Action overdue')).toBeVisible()
  await expect(page.locator('.compact-facts > div', { hasText: 'Action overdue' }).locator('dd')).toHaveText('1')
  await expect(page.getByText('metadata')).toHaveCount(0)
})

test('Workbench request failure surfaces safely without inventing fallback work', async ({ page }) => {
  await stubReadySession(page)
  await page.route('**/api/v1/me/workbench', (route) => fulfillJson(route, 500, { detail: 'Projection unavailable' }))

  await page.goto('/me/workbench')
  await expect(page.getByRole('alert')).toContainText('Projection unavailable')
  await expect(page.getByText('Server Case A')).toHaveCount(0)
})

test.describe('device time zone differs from the display time zone', () => {
  test.use({ timezoneId: 'America/New_York' })

  test('a filled but non-existent Shanghai time blocks plan creation and keeps input and idempotency key', async ({ page }) => {
    await stubReadySession(page)
    await page.route('**/api/v1/review-catalog', (route) =>
      fulfillJson(route, 200, [
        { scenario_key: 'process_review', scenario_version: 1, display_name: '过程审查' },
      ]),
    )
    const requests: { key: string | null; body: Record<string, unknown> }[] = []
    await page.route('**/api/v1/review-plans', async (route) => {
      requests.push({
        key: await route.request().headerValue('Idempotency-Key'),
        body: route.request().postDataJSON() as Record<string, unknown>,
      })
      if (requests.length === 1) return route.abort('failed')
      return fulfillJson(route, 422, { detail: 'stop after capturing the request' })
    })

    await page.goto('/review-plans/new')
    const start = page.getByLabel('计划开始时间（可选）')
    const end = page.getByLabel('计划结束时间（可选）')
    await page.getByLabel('计划名称').fill('无效时间计划')
    await start.fill('2026-08-28T18:00')
    await page.getByRole('button', { name: '保存计划并继续' }).click()
    await expect.poll(() => requests.length).toBe(1)
    await expect(page.getByRole('button', { name: '重试保存计划' })).toBeEnabled()

    // 1986-05-04 02:00 上海进入夏令时直接跳到 03:00，02:30 不存在；格式合法，原生输入框不会拦截。
    await end.fill('1986-05-04T02:30')
    await page.getByRole('button', { name: '重试保存计划' }).click()
    await expect(page.getByRole('alert')).toHaveText(
      '计划结束时间无效：请填写存在的上海时间（Asia/Shanghai）。',
    )
    await expect(end).toHaveValue('1986-05-04T02:30')

    await end.fill('')
    await start.fill('1986-05-04T02:30')
    await page.getByRole('button', { name: '重试保存计划' }).click()
    await expect(page.getByRole('alert')).toHaveText(
      '计划开始时间无效：请填写存在的上海时间（Asia/Shanghai）。',
    )
    await expect(start).toHaveValue('1986-05-04T02:30')
    await expect(page.getByLabel('计划名称')).toHaveValue('无效时间计划')
    expect(requests).toHaveLength(1)

    await start.fill('2026-08-28T18:00')
    await page.getByRole('button', { name: '重试保存计划' }).click()
    await expect.poll(() => requests.length).toBe(2)
    expect(requests[1].body).toMatchObject({
      planned_start_at: '2026-08-28T10:00:00.000Z',
      planned_end_at: null,
    })
    expect(requests[1].key).not.toBeNull()
    expect(requests[1].key).toBe(requests[0].key)
  })

  test('plan dates are entered and shown as Asia/Shanghai wall time', async ({ page }) => {
    await stubReadySession(page)
    await page.route('**/api/v1/me/workbench', (route) =>
      fulfillJson(route, 200, { ...emptyWorkbench, as_of: '2026-08-28T10:00:00Z' }),
    )
    await page.goto('/me/workbench')
    await expect(page.getByText('数据时间 2026/08/28 18:00')).toBeVisible()

    await page.route('**/api/v1/review-catalog', (route) =>
      fulfillJson(route, 200, [
        { scenario_key: 'process_review', scenario_version: 1, display_name: '过程审查' },
      ]),
    )
    let planBody: Record<string, unknown> | null = null
    await page.route('**/api/v1/review-plans', async (route) => {
      planBody = route.request().postDataJSON() as Record<string, unknown>
      await fulfillJson(route, 422, { detail: 'stop after capturing the request' })
    })

    await page.goto('/review-plans/new')
    for (const label of ['计划开始时间（可选）', '计划结束时间（可选）']) {
      await expect(page.getByLabel(label)).toHaveAccessibleDescription(
        '以下时间均按上海时间（Asia/Shanghai）填写和显示。',
      )
    }
    await page.getByLabel('计划名称').fill('时区计划')
    await page.getByLabel('计划开始时间（可选）').fill('2026-08-28T18:00')
    await page.getByLabel('计划结束时间（可选）').fill('2026-09-01T09:30')
    await page.getByRole('button', { name: '保存计划并继续' }).click()

    await expect.poll(() => planBody).not.toBeNull()
    expect(planBody).toMatchObject({
      planned_start_at: '2026-08-28T10:00:00.000Z',
      planned_end_at: '2026-09-01T01:30:00.000Z',
    })
  })
})
