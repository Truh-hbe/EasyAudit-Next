import { expect, test, type Locator, type Page, type Route } from '@playwright/test'

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

// DatePicker 的日期框：键入文本后按 Enter 确认（不会提交表单）。
async function enterDateTime(input: Locator, text: string) {
  await input.fill(text)
  await input.press('Enter')
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

type ContrastTarget = { selector: string; pseudo?: string } | { text: string }

// 在页面内计算文字相对有效背景的对比度（WCAG 2.x）。page.evaluate 会序列化函数，所以必须自包含。
function measureContrast(targets: Record<string, ContrastTarget>) {
  type El = { parentElement: El | null }
  const doc = (globalThis as unknown as {
    document: { querySelector: (s: string) => El | null; querySelectorAll: (s: string) => El[] }
    getComputedStyle: (e: El, pseudo?: string) => Record<string, string>
  })
  const parse = (value: string): [number, number, number, number] => {
    const m = value.match(/rgba?\(([^)]+)\)/)
    const parts = m ? m[1].split(/[ ,/]+/).filter(Boolean).map(Number) : [0, 0, 0, 0]
    return [parts[0], parts[1], parts[2], parts[3] ?? 1]
  }
  const lum = ([r, g, b]: number[]) => {
    const f = (c: number) => ((c /= 255) <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
  }
  const ratio = (a: number[], b: number[]) => {
    const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
    return (hi + 0.05) / (lo + 0.05)
  }
  const backgroundOf = (element: El) => {
    let bg: [number, number, number] = [255, 255, 255]
    const chain: El[] = []
    for (let e: El | null = element; e; e = e.parentElement) chain.unshift(e)
    for (const e of chain) {
      const [r, g, b, a] = parse(doc.getComputedStyle(e).backgroundColor)
      if (a > 0) bg = [r * a + bg[0] * (1 - a), g * a + bg[1] * (1 - a), b * a + bg[2] * (1 - a)]
    }
    return bg
  }
  const byText = (text: string) =>
    Array.from(doc.document.querySelectorAll('main *, [data-contrast-probe] *')).find(
      (e) => (e as unknown as { textContent: string; children: { length: number } }).children.length === 0 &&
        (e as unknown as { textContent: string }).textContent === text,
    ) ?? null
  const result: Record<string, number> = {}
  for (const [name, target] of Object.entries(targets)) {
    const element = 'text' in target ? byText(target.text) : doc.document.querySelector(target.selector)
    if (!element) throw new Error(`element not found: ${name}`)
    const [r, g, b, a] = parse(doc.getComputedStyle(element, 'pseudo' in target ? target.pseudo : undefined).color)
    const bg = backgroundOf(element)
    const fg = [r * a + bg[0] * (1 - a), g * a + bg[1] * (1 - a), b * a + bg[2] * (1 - a)]
    result[name] = Math.round(ratio(fg, bg) * 100) / 100
  }
  return result
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
  await expect(page.getByText('关系 观察员')).toBeVisible()
  await expect(page.getByText('observer')).toHaveCount(0)
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
  await expect(page.getByText('正在读取审查活动')).toBeVisible()
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

test('审查活动列表：新建入口是链接，状态显示为中文 StatusTag', async ({ page }) => {
  await stubReadySession(page)
  await page.route((url) => url.pathname === '/api/v1/review-cases', async (route) => {
    await fulfillJson(route, 200, {
      items: [caseResponse('case-a', { title: 'Visible A', lifecycle: 'in_progress' })],
      total: 1,
      limit: 50,
      offset: 0,
    })
  })

  await page.goto('/review-cases')
  const create = page.getByRole('link', { name: '新建审查计划' })
  await expect(create).toHaveAttribute('href', '/review-plans/new')
  await expect(page.getByRole('button', { name: '新建审查计划' })).toHaveCount(0)
  const tag = page.getByText('审查中', { exact: true })
  await expect(tag).toBeVisible()
  await expect(tag).toHaveCSS('color', 'rgb(9, 88, 217)')
  await expect(page.getByText('in_progress')).toHaveCount(0)

  await create.click()
  await expect(page).toHaveURL(/\/review-plans\/new$/)
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
  await expect(page.getByText('正在确认访问权限')).toBeVisible()
  caseGate.resolve()
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
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
  await expect(page.getByText('正在确认访问权限')).toBeVisible()
  await expect(page.getByText('Authorized Case A')).toHaveCount(0)
  await expect(page.getByText('Case A Member')).toHaveCount(0)
  caseBGate.resolve()
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
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
  await expect(page.getByText('暂不支持当前版本的审查场景界面（过程审查 · process_review@99）。仍可查看审查活动的通用信息。')).toBeVisible()
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
  await expect(page.getByText('创建审查活动')).toBeVisible()
  await expect(page.getByText('整改项已逾期')).toBeVisible()
  await expect(page.getByText('整改项已逾期', { exact: true }).locator('..')).toHaveText(/整改项已逾期\s*[:：]?\s*1$/)
  await expect(page.getByText('metadata')).toHaveCount(0)
})

test('Workbench request failure surfaces safely without inventing fallback work', async ({ page }) => {
  await stubReadySession(page)
  await page.route('**/api/v1/me/workbench', (route) => fulfillJson(route, 500, { detail: 'Projection unavailable' }))

  await page.goto('/me/workbench')
  await expect(page.getByRole('alert')).toContainText('Projection unavailable')
  await expect(page.getByText('Server Case A')).toHaveCount(0)
})

test('Workbench refresh failure keeps old content for network errors but drops it on authorization loss', async ({ page }) => {
  await stubReadySession(page)
  let outcome: 200 | 403 | 'abort' = 200
  await page.route('**/api/v1/me/workbench', (route) => {
    if (outcome === 'abort') return route.abort('failed')
    if (outcome === 403) return fulfillJson(route, 403, { detail: 'Forbidden' })
    return fulfillJson(route, 200, {
      ...emptyWorkbench,
      case_responsibilities: [
        { id: 'case-a', title: 'Server Case A', lifecycle: 'in_progress', role_keys: ['observer'], planned_end_at: null },
      ],
    })
  })

  await page.goto('/me/workbench')
  await expect(page.getByText('Server Case A')).toBeVisible()
  outcome = 'abort'
  await page.getByRole('button', { name: '刷新' }).click()
  await expect(page.getByRole('alert')).toContainText('刷新失败')
  await expect(page.getByText('Server Case A')).toBeVisible()

  outcome = 200
  await page.getByRole('button', { name: '重新加载' }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByText('Server Case A')).toBeVisible()

  outcome = 403
  await page.getByRole('button', { name: '刷新' }).click()
  await expect(page.getByRole('alert')).toContainText('Forbidden')
  await expect(page.getByText('Server Case A')).toHaveCount(0)
})

test('Workbench first load exposes busy state and a status, and clears both when loaded', async ({ page }) => {
  await stubReadySession(page)
  const gate = createDeferred()
  await page.route('**/api/v1/me/workbench', async (route) => {
    await gate.promise
    await fulfillJson(route, 200, emptyWorkbench)
  })
  await page.goto('/me/workbench')
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(1)
  await expect(page.getByRole('status')).toHaveText('正在加载我的工作')
  gate.resolve()
  await expect(page.getByText('暂无我参与的审查。')).toBeVisible()
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0)
  await expect(page.getByRole('status')).toHaveCount(0)
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
    await enterDateTime(start, '2026/08/28 18:00')
    await page.getByRole('button', { name: '保存计划并继续' }).click()
    await expect.poll(() => requests.length).toBe(1)
    await expect(page.getByRole('button', { name: '重试保存计划' })).toBeEnabled()

    // 1986-05-04 02:00 上海进入夏令时直接跳到 03:00，02:30 不存在；格式合法，选择器本身不会拦截。
    await enterDateTime(end, '1986/05/04 02:30')
    await page.getByRole('button', { name: '重试保存计划' }).click()
    await expect(page.getByText('计划结束时间无效：请填写存在的上海时间（Asia/Shanghai）。')).toBeVisible()
    await expect(end).toBeFocused()
    await expect(end).toHaveValue('1986/05/04 02:30')

    await enterDateTime(end, '')
    await enterDateTime(start, '1986/05/04 02:30')
    await page.getByRole('button', { name: '重试保存计划' }).click()
    await expect(page.getByText('计划开始时间无效：请填写存在的上海时间（Asia/Shanghai）。')).toBeVisible()
    await expect(start).toBeFocused()
    await expect(start).toHaveValue('1986/05/04 02:30')
    await expect(page.getByLabel('计划名称')).toHaveValue('无效时间计划')
    expect(requests).toHaveLength(1)

    await enterDateTime(start, '2026/08/28 18:00')
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
    await enterDateTime(page.getByLabel('计划开始时间（可选）'), '2026/08/28 18:00')
    await enterDateTime(page.getByLabel('计划结束时间（可选）'), '2026/09/01 09:30')
    await page.getByRole('button', { name: '保存计划并继续' }).click()

    await expect.poll(() => planBody).not.toBeNull()
    expect(planBody).toMatchObject({
      planned_start_at: '2026-08-28T10:00:00.000Z',
      planned_end_at: '2026-09-01T01:30:00.000Z',
    })
  })
})

test('legacy element styles stay inside legacy page containers and never cross the ui-modern boundary', async ({ page }) => {
  await stubReadySession(page)
  await stubEmptyWorkbench(page)
  // 不依赖具体业务页面：任何页面都已加载全局样式表，边界由注入的 fixture 验证。
  await page.goto('/me/workbench')
  await expect(page.getByRole('heading', { name: '我的工作' })).toBeVisible()

  const styles = await page.evaluate(() => {
    const browser = globalThis as unknown as {
      document: {
        querySelector: (selector: string) => { insertAdjacentHTML: (where: string, html: string) => void }
        getElementById: (id: string) => unknown
      }
      getComputedStyle: (element: unknown) => Record<string, string>
    }
    const fixture = (prefix: string) =>
      `<form id="${prefix}-form"><label id="${prefix}-label">名称<input id="${prefix}-input" /></label>` +
      `<button id="${prefix}-button" type="button" disabled>提交</button></form>`
    browser.document
      .querySelector('body')
      .insertAdjacentHTML(
        'beforeend',
        `<div class="surface-page">${fixture('legacy')}<div class="ui-modern">${fixture('modern')}</div></div>`,
      )
    const read = (id: string) => browser.getComputedStyle(browser.document.getElementById(id))
    const pick = (prefix: string) => ({
      formDisplay: read(`${prefix}-form`).display,
      labelWeight: read(`${prefix}-label`).fontWeight,
      inputPadding: read(`${prefix}-input`).padding,
      buttonOpacity: read(`${prefix}-button`).opacity,
    })
    return { legacy: pick('legacy'), modern: pick('modern') }
  })

  expect(styles.legacy).toEqual({
    formDisplay: 'grid',
    labelWeight: '650',
    inputPadding: '12px 14px',
    buttonOpacity: '0.5',
  })
  expect(styles.modern.formDisplay).toBe('block')
  expect(styles.modern.labelWeight).not.toBe('650')
  expect(styles.modern.inputPadding).not.toBe('12px 14px')
  expect(styles.modern.buttonOpacity).toBe('1')
})

test('shell switches navigation layout at the 992px breakpoint without document overflow', async ({ page }) => {
  await stubReadySession(page, 'system_admin')
  await stubEmptyWorkbench(page)
  await page.goto('/me/workbench')
  const nav = page.getByRole('navigation', { name: '主要导航' })
  const names = ['我的工作', '审查活动', '通知', '管理视图', '管理设置']

  for (const [width, direction] of [[992, 'column'], [991, 'row']] as const) {
    await page.setViewportSize({ width, height: 800 })
    await expect(nav).toHaveCSS('flex-direction', direction)
    for (const name of names) {
      await expect(nav.getByRole('link', { name })).toBeVisible()
    }
    const overflow = await page.evaluate(() => {
      const root = (globalThis as unknown as { document: { documentElement: { scrollWidth: number; clientWidth: number } } })
        .document.documentElement
      return root.scrollWidth - root.clientWidth
    })
    expect(overflow).toBeLessThanOrEqual(1)
  }
})

test('system admin can traverse all five primary navigation links with Tab and open one with Enter', async ({ page }) => {
  await stubReadySession(page, 'system_admin')
  await stubEmptyWorkbench(page)
  await page.goto('/me/workbench')
  const nav = page.getByRole('navigation', { name: '主要导航' })
  const names = ['我的工作', '审查活动', '通知', '管理视图', '管理设置']

  await nav.getByRole('link', { name: names[0] }).focus()
  for (const [index, name] of names.entries()) {
    if (index > 0) await page.keyboard.press('Tab')
    await expect(nav.getByRole('link', { name })).toBeFocused()
  }
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/admin$/)
})

async function stubAnonymous(page: Page) {
  await page.route('**/api/v1/me', (route) =>
    fulfillJson(route, 401, { detail: 'Authentication required' }),
  )
}

async function horizontalOverflow(page: Page) {
  return page.evaluate(() => {
    const root = (globalThis as unknown as { document: { documentElement: { scrollWidth: number; clientWidth: number } } })
      .document.documentElement
    return root.scrollWidth - root.clientWidth
  })
}

test('auth pages have no horizontal overflow and keep controls reachable at 375px and 320px', async ({ page }) => {
  await stubAnonymous(page)
  for (const width of [375, 320]) {
    await page.setViewportSize({ width, height: 700 })
    await page.goto('/login')
    await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
    expect(await horizontalOverflow(page)).toBeLessThanOrEqual(1)
    const box = await page.getByRole('button', { name: '登录' }).boundingBox()
    expect(box).not.toBeNull()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(width)
  }

  await page.unroute('**/api/v1/me')
  await page.route('**/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...user, must_change_password: true }),
  )
  for (const width of [375, 320]) {
    await page.setViewportSize({ width, height: 700 })
    await page.goto('/me/credential-remediation')
    await expect(page.getByRole('heading', { name: '需要修改密码' })).toBeVisible()
    expect(await horizontalOverflow(page)).toBeLessThanOrEqual(1)
    await page.getByRole('button', { name: '修改密码' }).click()
    await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible()
    expect(await horizontalOverflow(page)).toBeLessThanOrEqual(1)
  }
})

test('auth page text, placeholder, alert and link colors meet WCAG AA contrast', async ({ page }) => {
  await stubAnonymous(page)
  await page.route('**/api/v1/auth/login', (route) =>
    fulfillJson(route, 401, { detail: 'Invalid login name or password' }),
  )
  await page.goto('/login')
  const loginName = page.getByLabel('登录名')
  await loginName.evaluate((element) => element.setAttribute('placeholder', '例如 zhang.san'))
  await page.getByLabel('密码').fill('wrong-password')
  await loginName.fill('wrong-user')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByRole('alert')).toHaveText('登录名或密码无效')
  await loginName.fill('')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByText('请输入登录名')).toBeVisible()

  const ratios = await page.evaluate(measureContrast, {
    inputText: { selector: 'input[autocomplete="username"]' },
    placeholder: { selector: 'input[autocomplete="username"]', pseudo: '::placeholder' },
    label: { text: '登录名' },
    alert: { text: '登录名或密码无效' },
    fieldError: { text: '请输入登录名' },
    brand: { text: 'EasyAudit Next' },
  })

  for (const [name, ratio] of Object.entries(ratios)) {
    expect(ratio, name).toBeGreaterThanOrEqual(4.5)
  }
  console.log('auth contrast', JSON.stringify(ratios))
})

test('antd description text meets WCAG AA contrast on white and layout backgrounds', async ({ page }) => {
  await stubAnonymous(page)
  await page.goto('/login')
  await page.evaluate(async () => {
    // 由 `vite build --mode e2e` 注入的钩子加载探针（见 tests/e2e/e2eHook.ts）。
    const hook = (
      globalThis as unknown as {
        __easyauditE2E?: { loadThemeProbe: () => Promise<{ mountThemeProbe: () => void }> }
      }
    ).__easyauditE2E
    if (hook === undefined) throw new Error('e2e hook missing: run against `vite build --mode e2e`')
    ;(await hook.loadThemeProbe()).mountThemeProbe()
  })
  const ratios = await page.evaluate(measureContrast, {
    'secondary on white': { text: 'white-secondary' },
    'form extra on white': { text: 'white-extra' },
    'descriptions label on white': { text: 'white-label' },
    'secondary on layout': { text: 'layout-secondary' },
    'form extra on layout': { text: 'layout-extra' },
    'descriptions label on layout': { text: 'layout-label' },
  })
  for (const [name, ratio] of Object.entries(ratios)) {
    expect(ratio, name).toBeGreaterThanOrEqual(4.5)
  }
  console.log('description contrast', JSON.stringify(ratios))
})

test('antd built-in interactive icons meet WCAG 1.4.11 contrast and hover never gets lighter', async ({ page }) => {
  await stubAnonymous(page)
  await page.goto('/login')
  await page.evaluate(async () => {
    const hook = (
      globalThis as unknown as {
        __easyauditE2E?: { loadThemeProbe: () => Promise<{ mountThemeProbe: () => void }> }
      }
    ).__easyauditE2E
    if (hook === undefined) throw new Error('e2e hook missing: run against `vite build --mode e2e`')
    ;(await hook.loadThemeProbe()).mountThemeProbe()
  })
  // hoverOn 为空时直接悬停图标本身；清除按钮需要先悬停所在控件才可交互。
  const icons: Record<string, { selector: string; hoverOn?: string }> = {
    'password toggle': { selector: '[data-contrast-probe="white"] .ant-input-password-icon' },
    'password toggle on layout section': { selector: '[data-contrast-probe="layout"] .ant-input-password-icon' },
    'input clear': { selector: '[data-contrast-probe="icons"] .ant-input-clear-icon', hoverOn: '.ant-input-affix-wrapper' },
    'select arrow': { selector: '[data-contrast-probe="icons"] .ant-select-suffix' },
    'select clear': { selector: '[data-contrast-probe="icons"] .ant-select-clear', hoverOn: '.ant-select' },
    'picker suffix': { selector: '[data-contrast-probe="icons"] .ant-picker-suffix' },
    'picker clear': { selector: '[data-contrast-probe="icons"] .ant-picker-clear', hoverOn: '.ant-picker' },
    'table sorter': { selector: '[data-contrast-probe="icons"] .ant-table-column-sorter' },
    'table filter': { selector: '[data-contrast-probe="icons"] .ant-table-filter-trigger' },
  }
  const normal = await page.evaluate(
    measureContrast,
    Object.fromEntries(Object.entries(icons).map(([name, { selector }]) => [name, { selector }])),
  )
  const hovered: Record<string, number> = {}
  for (const [name, { selector, hoverOn }] of Object.entries(icons)) {
    if (hoverOn) await page.locator(`[data-contrast-probe="icons"] ${hoverOn}`).first().hover()
    await page.locator(selector).first().hover({ force: true })
    await page.waitForTimeout(400)
    Object.assign(hovered, await page.evaluate(measureContrast, { [name]: { selector } }))
    expect(normal[name], `${name} normal`).toBeGreaterThanOrEqual(3)
    expect(hovered[name], `${name} hover`).toBeGreaterThanOrEqual(3)
    expect(hovered[name], `${name} hover not lighter`).toBeGreaterThanOrEqual(normal[name])
  }
  // 组件级覆盖不得连带加深禁用态文字（colorTextDisabled 仍是 25%）。
  await expect(page.locator('[data-contrast-probe="icons"] input[disabled]')).toHaveCSS('color', 'rgba(23, 32, 51, 0.25)')
  console.log('icon contrast', JSON.stringify({ normal, hovered }))
})

test('password remediation keeps entered values on 422 and blocks mismatched confirmation', async ({ page }) => {
  let submissions = 0
  await page.route('**/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...user, must_change_password: true }),
  )
  await page.route('**/api/v1/me/password', async (route) => {
    submissions += 1
    await new Promise((resolve) => setTimeout(resolve, 300))
    await fulfillJson(route, 422, { detail: 'Password does not meet policy' })
  })

  await page.goto('/me/credential-remediation')
  await page.getByLabel('当前密码').fill('initial-password')
  await page.getByLabel('新密码', { exact: true }).fill('replacement-password')
  await page.getByLabel('确认新密码').fill('different-password')
  await page.getByRole('button', { name: '修改密码' }).click()
  await expect(page.getByText('两次输入的新密码不一致')).toBeVisible()
  await expect(page.getByLabel('确认新密码')).toBeFocused()
  expect(submissions).toBe(0)

  await page.getByLabel('确认新密码').fill('replacement-password')
  const submit = page.getByRole('button', { name: '修改密码' })
  await submit.dblclick()
  await expect(page.getByRole('alert')).toHaveText('Password does not meet policy')
  expect(submissions).toBe(1)
  await expect(page.getByLabel('当前密码')).toHaveValue('initial-password')
  await expect(page.getByLabel('新密码', { exact: true })).toHaveValue('replacement-password')
})

test('login focuses the first invalid field after a failed submit', async ({ page }) => {
  await stubAnonymous(page)
  await page.goto('/login')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByText('请输入登录名')).toBeVisible()
  await expect(page.getByLabel('登录名')).toBeFocused()

  await page.getByLabel('登录名').fill('someone')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByText('请输入密码')).toBeVisible()
  await expect(page.getByLabel('密码')).toBeFocused()
})
