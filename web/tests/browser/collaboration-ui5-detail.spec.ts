import { expect, test, type Page, type Route } from '@playwright/test'

import { openAssignDrawer, pickCandidate } from './assignmentDrawer.js'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'UI5 User',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
}

function fulfillJson(route: Route, status: number, body: unknown, headers: Record<string, string> = {}) {
  return route.fulfill({ status, contentType: 'application/json', headers, body: JSON.stringify(body) })
}

async function stubSession(page: Page) {
  await page.route((url) => url.pathname === '/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...user, must_change_password: false }),
  )
}

function caseResponse(scenarioKey: string) {
  return {
    id: 'case-ui5',
    organization_id: user.organization_id,
    plan_id: null,
    scenario_key: scenarioKey,
    scenario_version: 1,
    title: 'UI5 Case',
    lifecycle: 'in_progress',
    planned_start_at: null,
    planned_end_at: null,
    started_at: '2026-08-28T00:00:00Z',
    fieldwork_completed_at: null,
    closed_at: null,
    scenario_data:
      scenarioKey === 'process_review'
        ? { area_code: 'A-01', review_type: 'routine' }
        : { standard_reference: 'ISO 9001', scope_summary: 'Assembly line' },
    created_by: user.id,
    created_at: '2026-08-28T00:00:00Z',
  }
}

function findingResponse(scenarioKey: string, lifecycle: string, findingType = 'nonconformity') {
  return {
    id: 'finding-ui5',
    organization_id: user.organization_id,
    case_id: 'case-ui5',
    title: 'UI5 Finding',
    description: 'Description text',
    severity: 'high',
    lifecycle,
    scenario_data:
      scenarioKey === 'process_review'
        ? { issue_type: 'control_gap', project_category: 'assembly' }
        : { criterion_reference: '8.5.1', finding_type: findingType },
    raised_by: user.id,
    raised_at: '2026-08-28T01:00:00Z',
  }
}

function actionResponse(lifecycle: string) {
  return {
    id: 'action-ui5',
    organization_id: user.organization_id,
    finding_id: 'finding-ui5',
    title: 'UI5 Action',
    lifecycle,
    due_at: '2026-08-30T00:00:00Z',
    completed_at: lifecycle === 'done' ? '2026-08-29T00:00:00Z' : null,
  }
}

interface FindingWorld {
  scenarioKey: string
  findingType: string
  lifecycle: string
  posts: { path: string; body: unknown }[]
}

// 有状态的发现项 stub：提交命令后按领域规则推进 lifecycle，页面只能通过刷新看到。
async function stubFindingWorld(page: Page, world: FindingWorld) {
  await stubSession(page)
  await page.route((url) => url.pathname === '/api/v1/findings/finding-ui5', (route) =>
    fulfillJson(route, 200, findingResponse(world.scenarioKey, world.lifecycle, world.findingType)),
  )
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-ui5', (route) =>
    fulfillJson(route, 200, caseResponse(world.scenarioKey)),
  )
  for (const child of ['participant-views', 'actions', 'submissions', 'activities']) {
    await page.route((url) => url.pathname === `/api/v1/findings/finding-ui5/${child}`, (route) =>
      fulfillJson(route, 200, []),
    )
  }
  const next: Record<string, string> = {
    transitions: '',
    'rectification-submissions': 'verifying',
    'verification-submissions': 'closed',
    reopen: 'rectifying',
  }
  for (const command of Object.keys(next)) {
    await page.route((url) => url.pathname === `/api/v1/findings/finding-ui5/${command}`, (route) => {
      const body = route.request().postDataJSON() as { action?: string }
      world.posts.push({ path: command, body })
      if (command === 'transitions') {
        world.lifecycle = body.action === 'issue' ? 'rectifying' : body.action === 'void' ? 'voided' : 'closed'
      } else if (command === 'rectification-submissions') {
        if (body.action === 'submit_for_verification') world.lifecycle = 'verifying'
      } else if (command === 'verification-submissions') {
        world.lifecycle = body.action === 'approve' ? 'closed' : 'rectifying'
      } else {
        world.lifecycle = world.findingType === 'observation' ? 'open' : 'rectifying'
      }
      return fulfillJson(route, 200, findingResponse(world.scenarioKey, world.lifecycle, world.findingType))
    })
  }
}

const header = (page: Page) => page.getByRole('article').locator('header')

test('compliance_review@1 observation closes directly after an explicit confirmation, without Action or rectification', async ({ page }) => {
  const world: FindingWorld = { scenarioKey: 'compliance_review', findingType: 'observation', lifecycle: 'open', posts: [] }
  await stubFindingWorld(page, world)

  await page.goto('/findings/finding-ui5')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('UI5 Finding')
  await expect(header(page).getByText('观察项')).toBeVisible()
  await expect(page.getByRole('button', { name: '签发不符合项' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '填写整改计划' })).toHaveCount(0)

  await page.getByRole('button', { name: '接受观察项' }).click()
  const confirm = page.getByRole('dialog', { name: '接受观察项' })
  await expect(confirm).toContainText('不需要整改项')
  await expect(confirm).not.toContainText('不能重新打开') // 领域规则允许 closed → reopen
  expect(world.posts).toHaveLength(0) // 确认前不发请求
  await confirm.getByRole('button', { name: '确认接受并关闭' }).click()

  await expect(header(page).getByText('已关闭', { exact: true })).toBeVisible()
  await expect(page.getByText('观察项已接受并闭环。')).toBeVisible()
  const reopenButton = page.getByRole('button', { name: '重新打开', exact: true })
  await reopenButton.click()
  const reopen = page.getByRole('dialog', { name: '重新打开发现项' })
  await reopen.getByLabel('重新打开原因').fill('follow-up')
  await reopen.getByRole('button', { name: '确认重新打开' }).click()

  // 重开后回到待处理，可再次接受，不进入整改
  await expect(header(page).getByText('待处理', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '接受观察项' })).toBeVisible()
  await expect(page.getByRole('button', { name: '填写整改计划' })).toHaveCount(0)
  expect(world.posts.map((post) => post.path)).toEqual(['transitions', 'reopen'])
})

test('compliance_review@1 nonconformity goes issue → plan/completion → approve → reopen', async ({ page }) => {
  const world: FindingWorld = { scenarioKey: 'compliance_review', findingType: 'nonconformity', lifecycle: 'open', posts: [] }
  await stubFindingWorld(page, world)

  await page.goto('/findings/finding-ui5')
  await expect(page.getByText('8.5.1')).toBeVisible()
  await page.getByRole('button', { name: '签发不符合项' }).click()
  await expect(header(page).getByText('整改中', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '提交整改完成' }).click()
  const completion = page.getByRole('dialog', { name: '整改完成' })
  await completion.getByLabel('整改完成说明').fill('done')
  await completion.getByRole('button', { name: '提交验证' }).click()
  await expect(header(page).getByText('待验证', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '通过验证' }).click()
  await page.getByRole('dialog', { name: '通过验证' }).getByRole('button', { name: '确认通过' }).click()
  await expect(header(page).getByText('已关闭', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '重新打开', exact: true }).click()
  const reopen = page.getByRole('dialog', { name: '重新打开发现项' })
  await reopen.getByLabel('重新打开原因').fill('follow-up')
  await reopen.getByRole('button', { name: '确认重新打开' }).click()
  await expect(header(page).getByText('整改中', { exact: true })).toBeVisible()

  expect(world.posts.map((post) => post.path)).toEqual([
    'transitions',
    'rectification-submissions',
    'verification-submissions',
    'reopen',
  ])
})

test('process_review@1 void asks for a reason in a confirmation dialog and sends it', async ({ page }) => {
  const world: FindingWorld = { scenarioKey: 'process_review', findingType: '', lifecycle: 'open', posts: [] }
  await stubFindingWorld(page, world)

  await page.goto('/findings/finding-ui5')
  await expect(page.getByText('control_gap')).toBeVisible()
  await page.getByRole('button', { name: '作废发现项' }).click()
  const dialog = page.getByRole('dialog', { name: '作废发现项' })
  await dialog.getByLabel('作废原因').fill('duplicate')
  await dialog.getByRole('button', { name: '确认作废' }).click()

  await expect(header(page).getByText('已作废', { exact: true })).toBeVisible()
  expect(world.posts).toEqual([{ path: 'transitions', body: { action: 'void', reason: 'duplicate' } }])
})

async function stubActionWorld(page: Page, state: { lifecycle: string; posts: unknown[] }, evidenceStatus = 200) {
  await stubSession(page)
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5', (route) =>
    fulfillJson(route, 200, actionResponse(state.lifecycle)),
  )
  await page.route((url) => url.pathname === '/api/v1/findings/finding-ui5', (route) =>
    fulfillJson(route, 200, findingResponse('process_review', 'rectifying')),
  )
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-ui5', (route) =>
    fulfillJson(route, 200, caseResponse('process_review')),
  )
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/assignee-views', (route) =>
    fulfillJson(route, 200, [
      {
        action_item_id: 'action-ui5',
        actor_kind: 'user',
        actor_id: user.id,
        role: 'primary',
        assigned_at: '2026-08-28T04:00:00Z',
        display_name: 'Primary Executor',
      },
    ]),
  )
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/activities', (route) =>
    fulfillJson(route, 200, []),
  )
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/evidences', (route) =>
    evidenceStatus === 200
      ? fulfillJson(route, 200, [
          {
            id: 'evidence-ui5',
            organization_id: user.organization_id,
            action_item_id: 'action-ui5',
            storage_key: 'private/key',
            original_name: '整改报告.pdf',
            content_type: 'application/pdf',
            size_bytes: 9,
            sha256: 'a'.repeat(64),
            description: null,
            uploaded_by: user.id,
            created_at: '2026-10-01T03:00:00Z',
          },
        ])
      : fulfillJson(route, evidenceStatus, { detail: 'Forbidden' }),
  )
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/transitions', (route) => {
    const body = route.request().postDataJSON() as { action: string; reason: string | null }
    state.posts.push(body)
    state.lifecycle = { start: 'in_progress', complete: 'done', reopen: 'in_progress', cancel: 'cancelled' }[body.action] ?? state.lifecycle
    return fulfillJson(route, 200, actionResponse(state.lifecycle))
  })
}

test('Action runs start → complete → reopen and shows executor, due time and completion requirement first', async ({ page }) => {
  const state = { lifecycle: 'todo', posts: [] as unknown[] }
  await stubActionWorld(page, state)

  await page.goto('/action-items/action-ui5')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('UI5 Action')
  const overview = page.getByRole('region', { name: '整改事项' })
  for (const label of ['任务', '执行人', '截止时间', '完成要求']) {
    await expect(overview.getByText(label, { exact: true })).toBeVisible()
  }
  await expect(overview.getByText('Primary Executor')).toBeVisible()

  await page.getByRole('button', { name: '开始整改项', exact: true }).click()
  await expect(header(page).getByText('执行中', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '完成整改项', exact: true }).click()
  await expect(header(page).getByText('已完成', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '重新打开整改项', exact: true }).click()
  await page.getByRole('dialog', { name: '重新打开整改项' }).getByRole('button', { name: '确认重新打开' }).click()
  await expect(header(page).getByText('执行中', { exact: true })).toBeVisible()
  expect(state.posts).toEqual([
    { action: 'start', reason: null },
    { action: 'complete', reason: null },
    { action: 'reopen', reason: null },
  ])
})

test('cancelling an Action is irreversible: a dialog collects the reason before anything is sent', async ({ page }) => {
  const state = { lifecycle: 'in_progress', posts: [] as unknown[] }
  await stubActionWorld(page, state)

  await page.goto('/action-items/action-ui5')
  await page.getByRole('button', { name: '取消整改项' }).click()
  const dialog = page.getByRole('dialog', { name: '取消整改项' })
  expect(state.posts).toHaveLength(0)
  await dialog.getByLabel('取消原因').fill('no longer needed')
  await dialog.getByRole('button', { name: '确认取消' }).click()
  await expect(header(page).getByText('已取消', { exact: true })).toBeVisible()
  expect(state.posts).toEqual([{ action: 'cancel', reason: 'no longer needed' }])
})

test('evidence download is a same-origin attachment link; without access there is no entry', async ({ page }) => {
  const state = { lifecycle: 'in_progress', posts: [] as unknown[] }
  await stubActionWorld(page, state)
  await page.goto('/action-items/action-ui5')
  const link = page.getByRole('link', { name: '下载 整改报告.pdf' })
  await expect(link).toHaveAttribute('href', '/api/v1/evidences/evidence-ui5/content')

  const denied = await page.context().newPage()
  await stubActionWorld(denied, state, 403)
  await denied.goto('/action-items/action-ui5')
  await expect(denied.getByText('证据不可用。')).toBeVisible()
  await expect(denied.getByRole('link', { name: /下载/ })).toHaveCount(0)
  await expect(denied.getByRole('button', { name: '选择文件' })).toBeVisible() // 上传入口是否可用仍由服务器授权决定
})

test('selecting a file does not send it; only the explicit button uploads', async ({ page }) => {
  const state = { lifecycle: 'in_progress', posts: [] as unknown[] }
  await stubActionWorld(page, state)
  let uploads = 0
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/evidence-uploads', (route) => {
    uploads += 1
    return fulfillJson(route, 413, { detail: 'too big' })
  })
  await page.goto('/action-items/action-ui5')
  await page.getByLabel('证据文件').setInputFiles({ name: '中文 报告.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF') })
  await expect(page.getByText('中文 报告.pdf')).toBeVisible()
  await expect(page.getByText(/%/)).toHaveCount(0) // 没有真实进度，不显示百分比
  await page.waitForTimeout(300)
  expect(uploads).toBe(0)
  await expect(page.getByRole('button', { name: '上传证据' })).toBeEnabled()
})

const failureCases = [
  { name: '403', status: 403, headers: {} as Record<string, string>, expected: '当前账号没有执行此操作的权限。' },
  { name: '429 with Retry-After', status: 429, headers: { 'Retry-After': '30' }, expected: '30 秒后手动重试' },
  { name: '503 with Retry-After', status: 503, headers: { 'Retry-After': '12' }, expected: '12 秒后手动重试' },
  { name: '409', status: 409, headers: {} as Record<string, string>, expected: '数据已变化，正在获取最新状态', detail: 'Concurrent ActionItem transition' },
]

for (const failure of failureCases) {
  test(`write failure ${failure.name} is explained and never replayed`, async ({ page }) => {
    const state = { lifecycle: 'todo', posts: [] as unknown[] }
    await stubActionWorld(page, state)
    let attempts = 0
    await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/transitions', (route) => {
      attempts += 1
      return fulfillJson(route, failure.status, { detail: failure.detail ?? 'Forbidden' }, failure.headers)
    })
    await page.goto('/action-items/action-ui5')
    await page.getByRole('button', { name: '开始整改项', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText(failure.expected)
    await page.waitForTimeout(400)
    expect(attempts).toBe(1)
  })
}

test('write 404 removes protected content and shows the neutral unavailable Result', async ({ page }) => {
  const state = { lifecycle: 'todo', posts: [] as unknown[] }
  await stubActionWorld(page, state)
  let gone = false
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5', (route) =>
    gone ? fulfillJson(route, 404, { detail: 'not found' }) : fulfillJson(route, 200, actionResponse('todo')),
  )
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/transitions', (route) => {
    gone = true
    return fulfillJson(route, 404, { detail: 'not found' })
  })
  await page.goto('/action-items/action-ui5')
  await page.getByRole('button', { name: '开始整改项', exact: true }).click()
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByText('Primary Executor')).toHaveCount(0)
  await expect(page.getByRole('link', { name: '下载 整改报告.pdf' })).toHaveCount(0)
})

test('a dropped connection on a command says the outcome is unconfirmed and does not retry', async ({ page }) => {
  const state = { lifecycle: 'todo', posts: [] as unknown[] }
  await stubActionWorld(page, state)
  let attempts = 0
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/transitions', (route) => {
    attempts += 1
    return route.abort('connectionreset')
  })
  await page.goto('/action-items/action-ui5')
  await page.getByRole('button', { name: '开始整改项', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('未确认开始整改项是否成功')
  await page.waitForTimeout(400)
  expect(attempts).toBe(1)
})

test('assignee drawer maps a 422 rule code to a Chinese alert and keeps the dialog open', async ({ page }) => {
  const state = { lifecycle: 'todo', posts: [] as unknown[] }
  await stubActionWorld(page, state)
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/assignee-candidates', (route) =>
    fulfillJson(route, 200, [{ actor_kind: 'user', actor_id: 'cand', display_name: 'Candidate User' }]),
  )
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/assignees', (route) =>
    fulfillJson(route, 422, { detail: 'Assignee not eligible', code: 'role.not_allowed_for_actor', params: {}, errors: [] }),
  )
  await page.goto('/action-items/action-ui5')
  const drawer = await openAssignDrawer(page, '添加执行人', '添加执行人')
  await pickCandidate(drawer, '执行人', 'Candidate', 'Candidate User')
  await drawer.getByRole('button', { name: '添加执行人' }).click()
  await expect(drawer.getByRole('alert')).toContainText('所选对象不能担任该角色，请重新选择。')
  expect(await page.getByText('Assignee not eligible').count()).toBe(0)
  await expect(drawer).toBeVisible()
})

for (const [width, height] of [[375, 812], [320, 740], [640, 800]] as const) {
  test(`Finding and Action detail pages have no page-level horizontal overflow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const world: FindingWorld = { scenarioKey: 'compliance_review', findingType: 'nonconformity', lifecycle: 'rectifying', posts: [] }
    await stubFindingWorld(page, world)
    const state = { lifecycle: 'in_progress', posts: [] as unknown[] }
    await stubActionWorld(page, state)
    const overflow = () =>
      page.evaluate(() => {
        const root = (globalThis as unknown as { document: { documentElement: { scrollWidth: number; clientWidth: number } } }).document.documentElement
        return root.scrollWidth - root.clientWidth
      })
    for (const path of ['/findings/finding-ui5', '/action-items/action-ui5']) {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
      expect(await overflow()).toBeLessThanOrEqual(1)
    }
    await page.goto('/findings/finding-ui5')
    await page.getByRole('button', { name: '提交整改完成' }).click()
    await expect(page.getByRole('dialog', { name: '整改完成' }).getByLabel('整改完成说明')).toBeVisible()
    expect(await overflow()).toBeLessThanOrEqual(1)
  })
}

test('approve and Action reopen need a confirmation: 0 requests before and after cancel, exactly 1 after confirm', async ({ page }) => {
  const world: FindingWorld = { scenarioKey: 'process_review', findingType: '', lifecycle: 'verifying', posts: [] }
  await stubFindingWorld(page, world)
  await page.goto('/findings/finding-ui5')

  await page.getByRole('button', { name: '通过验证' }).click()
  const approve = page.getByRole('dialog', { name: '通过验证' })
  await expect(approve).toContainText('发现项将关闭')
  expect(world.posts).toHaveLength(0)
  await approve.getByRole('button', { name: /^取\s*消$/ }).click()
  await expect(approve).toHaveCount(0)
  await page.waitForTimeout(200)
  expect(world.posts).toHaveLength(0)
  await page.getByRole('button', { name: '通过验证' }).click()
  await page.getByRole('dialog', { name: '通过验证' }).getByRole('button', { name: '确认通过' }).click()
  await expect(header(page).getByText('已关闭', { exact: true })).toBeVisible()
  expect(world.posts.map((post) => post.path)).toEqual(['verification-submissions'])

  const state = { lifecycle: 'done', posts: [] as unknown[] }
  const other = await page.context().newPage()
  await stubActionWorld(other, state)
  await other.goto('/action-items/action-ui5')
  await other.getByRole('button', { name: '重新打开整改项', exact: true }).click()
  const reopen = other.getByRole('dialog', { name: '重新打开整改项' })
  await expect(reopen).toContainText('回到执行中')
  expect(state.posts).toHaveLength(0)
  await reopen.getByRole('button', { name: /^取\s*消$/ }).click()
  await other.waitForTimeout(200)
  expect(state.posts).toHaveLength(0)
  await other.getByRole('button', { name: '重新打开整改项', exact: true }).click()
  await other.getByRole('dialog', { name: '重新打开整改项' }).getByRole('button', { name: '确认重新打开' }).click()
  await expect(other.getByRole('article').locator('header').getByText('执行中', { exact: true })).toBeVisible()
  expect(state.posts).toEqual([{ action: 'reopen', reason: null }])
})

const conflicts = [
  { name: 'lifecycle or concurrent change', detail: 'Concurrent ActionItem transition', expected: '数据已变化，正在获取最新状态', refetch: true },
  { name: 'duplicate relation', detail: '(psycopg.errors.UniqueViolation) duplicate key value violates unique constraint "uq_assignee"', expected: '数据已变化，正在获取最新状态', refetch: true },
  { name: 'unclassified conflict', detail: 'some internal conflict: secret-detail', expected: '数据已变化，正在获取最新状态', refetch: true },
]

for (const conflict of conflicts) {
  test(`409 ${conflict.name} gets the same prompt, hides backend detail, refetches and never replays`, async ({ page }) => {
    const state = { lifecycle: 'todo', posts: [] as unknown[] }
    await stubActionWorld(page, state)
    let attempts = 0
    let reads = 0
    await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5', (route) => {
      reads += 1
      return fulfillJson(route, 200, actionResponse('todo'))
    })
    await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/transitions', (route) => {
      attempts += 1
      return fulfillJson(route, 409, { detail: conflict.detail })
    })
    await page.goto('/action-items/action-ui5')
    await page.getByRole('button', { name: '开始整改项', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText(conflict.expected)
    await expect(page.getByRole('alert')).not.toContainText('secret-detail')
    await expect(page.getByRole('alert')).not.toContainText('uq_assignee')
    await expect.poll(() => reads).toBeGreaterThanOrEqual(2) // 重新读取
    await page.waitForTimeout(300)
    expect(attempts).toBe(1)
  })
}

test('a write 403 shows a neutral prompt without backend detail and re-checks the primary resource', async ({ page }) => {
  const state = { lifecycle: 'todo', posts: [] as unknown[] }
  await stubActionWorld(page, state)
  let reads = 0
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5', (route) => {
    reads += 1
    return fulfillJson(route, 200, actionResponse('todo'))
  })
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/transitions', (route) =>
    fulfillJson(route, 403, { detail: 'Action primary role required' }),
  )
  await page.goto('/action-items/action-ui5')
  await page.getByRole('button', { name: '开始整改项', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('当前账号没有执行此操作的权限。')
  await expect(page.getByText('Action primary role required')).toHaveCount(0)
  await expect.poll(() => reads).toBeGreaterThanOrEqual(2)
  await expect(page.getByRole('region', { name: '整改事项' }).getByText('Primary Executor')).toBeVisible() // 仍有读权限：内容保留
})

for (const failure of [
  { status: 429, retryAfter: '30', expected: '30 秒后手动重试' },
  { status: 503, retryAfter: '12', expected: '12 秒后手动重试' },
]) {
  test(`upload ${failure.status} shows the Retry-After wait and is not retried`, async ({ page }) => {
    const state = { lifecycle: 'in_progress', posts: [] as unknown[] }
    await stubActionWorld(page, state)
    let attempts = 0
    await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/evidence-uploads', (route) => {
      attempts += 1
      return fulfillJson(route, failure.status, { detail: 'busy' }, { 'Retry-After': failure.retryAfter })
    })
    await page.goto('/action-items/action-ui5')
    await page.getByLabel('证据文件').setInputFiles({ name: 'scan.pdf', mimeType: 'application/pdf', buffer: Buffer.from('data') })
    await page.getByRole('button', { name: '上传证据' }).click()
    await expect(page.getByRole('alert')).toContainText(failure.expected)
    await page.waitForTimeout(400)
    expect(attempts).toBe(1)
    await expect(page.getByRole('button', { name: '上传证据' })).toBeEnabled()
  })
}

test('an upload result that arrives after switching Action is discarded and not written to the new Action', async ({ page }) => {
  const state = { lifecycle: 'in_progress', posts: [] as unknown[] }
  await stubActionWorld(page, state)
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5-b', (route) =>
    fulfillJson(route, 200, { ...actionResponse('in_progress'), id: 'action-ui5-b', title: 'UI5 Action B' }),
  )
  for (const child of ['assignee-views', 'activities', 'evidences']) {
    await page.route((url) => url.pathname === `/api/v1/action-items/action-ui5-b/${child}`, (route) =>
      fulfillJson(route, 200, []),
    )
  }
  let uploads = 0
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/evidence-uploads', async (route) => {
    uploads += 1
    await new Promise((resolve) => setTimeout(resolve, 400))
    return fulfillJson(route, 201, {
      id: 'late', organization_id: user.organization_id, action_item_id: 'action-ui5', storage_key: 'k',
      original_name: 'late.pdf', content_type: 'application/pdf', size_bytes: 4, sha256: 'b'.repeat(64),
      description: null, uploaded_by: user.id, created_at: '2026-10-01T03:00:00Z',
    })
  })
  await page.goto('/action-items/action-ui5')
  await page.getByLabel('证据文件').setInputFiles({ name: 'late.pdf', mimeType: 'application/pdf', buffer: Buffer.from('data') })
  await page.getByRole('button', { name: '上传证据' }).click()
  await expect.poll(() => uploads).toBe(1)

  await page.evaluate(
    "history.pushState({}, '', '/action-items/action-ui5-b'); dispatchEvent(new PopStateEvent('popstate'))",
  )
  await expect(page.getByRole('heading', { level: 1, name: 'UI5 Action B' })).toBeVisible()
  await page.waitForTimeout(600)
  await expect(page.getByText('服务器已确认上传')).toHaveCount(0)
  await expect(page.getByText('late.pdf')).toHaveCount(0)
  await expect(page.getByText('暂无证据。')).toBeVisible()
})

test('a refreshing section keeps its old content and says it is refreshing', async ({ page }) => {
  const world: FindingWorld = { scenarioKey: 'process_review', findingType: '', lifecycle: 'open', posts: [] }
  await stubFindingWorld(page, world)
  let participantReads = 0
  await page.route((url) => url.pathname === '/api/v1/findings/finding-ui5/participant-views', async (route) => {
    participantReads += 1
    if (participantReads > 1) await new Promise((resolve) => setTimeout(resolve, 800))
    return fulfillJson(route, 200, [
      { finding_id: 'finding-ui5', actor_kind: 'user', actor_id: user.id, role_key: 'owner', assigned_at: '2026-08-28T02:00:00Z', display_name: 'Kept Participant' },
    ])
  })
  await page.route((url) => url.pathname === '/api/v1/findings/finding-ui5/nudge', (route) =>
    fulfillJson(route, 200, { activity_id: 'activity-1', recipient_count: 1 }),
  )
  await page.goto('/findings/finding-ui5')
  const participants = page.getByRole('region', { name: '参与方' })
  await expect(participants.getByText('Kept Participant')).toBeVisible()
  await page.getByRole('button', { name: '催办', exact: true }).click()
  await expect(page.getByText('服务器已确认催办：已通知 1 人。')).toBeVisible()
  expect(await page.getByText('activity-1', { exact: false }).count()).toBe(0)
  await expect(participants.getByText('正在刷新')).toBeVisible()
  await expect(participants.getByText('Kept Participant')).toBeVisible()
  await expect(participants.getByText('正在刷新')).toHaveCount(0)
})

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

async function stubActionB(page: Page) {
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5-b', (route) =>
    fulfillJson(route, 200, { ...actionResponse('todo'), id: 'action-ui5-b', title: 'UI5 Action B' }),
  )
  for (const child of ['assignee-views', 'activities', 'evidences']) {
    await page.route((url) => url.pathname === `/api/v1/action-items/action-ui5-b/${child}`, (route) =>
      fulfillJson(route, 200, []),
    )
  }
}

const navigateTo = (page: Page, path: string) =>
  page.evaluate(`history.pushState({}, '', ${JSON.stringify(path)}); dispatchEvent(new PopStateEvent('popstate'))`)

test('a reopen confirmation is destroyed when the Action becomes unavailable and can no longer write', async ({ page }) => {
  const state = { lifecycle: 'done', posts: [] as unknown[] }
  await stubActionWorld(page, state)
  let gone = false
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5', (route) =>
    gone ? fulfillJson(route, 403, { detail: 'Forbidden' }) : fulfillJson(route, 200, actionResponse('done')),
  )
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/nudge', async (route) => {
    await sleep(500)
    gone = true
    return fulfillJson(route, 200, { activity_id: 'a-1', recipient_count: 1 })
  })
  await page.goto('/action-items/action-ui5')
  await page.getByRole('button', { name: '催办', exact: true }).click() // 在途请求结束后会重读主资源
  await page.getByRole('button', { name: '重新打开整改项', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '重新打开整改项' })).toBeVisible()

  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(state.posts).toEqual([])
})

test('once the Action is unavailable, a command that finishes later neither refreshes nor reports success', async ({ page }) => {
  const state = { lifecycle: 'todo', posts: [] as unknown[] }
  await stubActionWorld(page, state)
  let gone = false
  let primaryReads = 0
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5', (route) => {
    primaryReads += 1
    return gone ? fulfillJson(route, 403, { detail: 'Forbidden' }) : fulfillJson(route, 200, actionResponse('todo'))
  })
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/nudge', (route) => {
    gone = true
    return fulfillJson(route, 200, { activity_id: 'a-1', recipient_count: 1 })
  })
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/transitions', async (route) => {
    await sleep(2500)
    return fulfillJson(route, 200, actionResponse('in_progress'))
  })
  await page.goto('/action-items/action-ui5')
  await page.getByRole('button', { name: '开始整改项', exact: true }).click()
  await page.getByRole('button', { name: '催办', exact: true }).click()
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  const readsAtDenial = primaryReads
  await sleep(3000) // 开始整改项的响应在拒绝之后才到
  expect(await page.getByText('已完成：开始整改项').count()).toBe(0) // 一次性检查：toHaveCount 会等提示自行消失而通过
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  expect(primaryReads).toBe(readsAtDenial)
})

test('a 403 on a dependent resource re-checks the primary resource, and its 403 removes the content', async ({ page }) => {
  const state = { lifecycle: 'todo', posts: [] as unknown[] }
  await stubActionWorld(page, state)
  let activitiesDenied = false
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/activities', (route) => {
    activitiesDenied = true
    return fulfillJson(route, 403, { detail: 'Forbidden' })
  })
  let primaryReads = 0
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5', (route) => {
    primaryReads += 1
    return activitiesDenied ? fulfillJson(route, 403, { detail: 'Forbidden' }) : fulfillJson(route, 200, actionResponse('todo'))
  })
  await page.goto('/action-items/action-ui5')
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByRole('heading', { name: '执行操作' })).toHaveCount(0)
  expect(primaryReads).toBeGreaterThanOrEqual(2)
})

test('a command still in flight after leaving Action A and coming back (A → B → A) is dropped and cannot release the lock of the new command', async ({ page }) => {
  const state = { lifecycle: 'todo', posts: [] as unknown[] }
  await stubActionWorld(page, state)
  await stubActionB(page)
  let transitions = 0
  let firstDone = false
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/transitions', async (route) => {
    transitions += 1
    const first = transitions === 1
    await sleep(first ? 2500 : 8000)
    if (first) setTimeout(() => (firstDone = true), 300) // 留出前端处理第一次响应的时间
    return fulfillJson(route, 200, actionResponse('todo'))
  })
  await page.goto('/action-items/action-ui5')
  await page.getByRole('button', { name: '开始整改项', exact: true }).click()
  await expect.poll(() => transitions).toBe(1)
  await navigateTo(page, '/action-items/action-ui5-b')
  await expect(page.getByRole('heading', { level: 1, name: 'UI5 Action B' })).toBeVisible()
  await navigateTo(page, '/action-items/action-ui5')
  await expect(page.getByRole('heading', { level: 1, name: 'UI5 Action' })).toBeVisible()
  await page.getByRole('button', { name: '开始整改项', exact: true }).click()
  await expect.poll(() => transitions).toBe(2)

  await expect.poll(() => firstDone).toBe(true)
  await expect(page.getByRole('button', { name: '开始整改项', exact: true })).toBeDisabled()
  expect(await page.getByText('已完成：开始整改项').count()).toBe(0) // 一次性检查：第二次命令稍后返回时才会合法地出现提示
})

test('a candidate search 403 with a still-readable Action shows a neutral prompt instead of a stale hint', async ({ page }) => {
  const state = { lifecycle: 'todo', posts: [] as unknown[] }
  await stubActionWorld(page, state)
  let primaryReads = 0
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5', (route) => {
    primaryReads += 1
    return fulfillJson(route, 200, actionResponse('todo'))
  })
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/assignee-candidates', (route) =>
    fulfillJson(route, 403, { detail: 'candidate role detail' }),
  )
  await page.goto('/action-items/action-ui5')
  const drawer = await openAssignDrawer(page, '添加执行人', '添加执行人')
  await drawer.getByRole('combobox', { name: '执行人' }).fill('Candidate')
  await expect(drawer.getByRole('alert')).toContainText('当前账号没有执行此操作的权限。')
  await expect(page.getByText('candidate role detail')).toHaveCount(0)
  await expect.poll(() => primaryReads).toBeGreaterThanOrEqual(2) // 重新校验主资源，仍可读
  await expect(drawer).toBeVisible()
})

test('creating an Action with an unknown outcome says to check the list first and does not replay', async ({ page }) => {
  const world: FindingWorld = { scenarioKey: 'process_review', findingType: '', lifecycle: 'rectifying', posts: [] }
  await stubFindingWorld(page, world)
  let creates = 0
  await page.route((url) => url.pathname === '/api/v1/findings/finding-ui5/actions', (route) => {
    if (route.request().method() !== 'POST') return fulfillJson(route, 200, [])
    creates += 1
    return route.abort('connectionreset')
  })
  await page.goto('/findings/finding-ui5')
  await page.getByRole('button', { name: '新建整改项' }).click()
  const drawer = page.getByRole('dialog', { name: '新建整改项' })
  await drawer.getByLabel('标题').fill('Maybe duplicated')
  await drawer.getByRole('button', { name: '创建整改项' }).click()
  await expect(drawer.getByRole('alert')).toContainText('请先刷新页面，在整改项列表中核对')
  await expect(drawer.getByRole('alert')).not.toContainText('可再次操作')
  await expect(drawer.getByLabel('标题')).toHaveValue('Maybe duplicated')
  await sleep(400)
  expect(creates).toBe(1)
})

test('a non-422 4xx on a command shows neutral text, never the backend detail', async ({ page }) => {
  const state = { lifecycle: 'todo', posts: [] as unknown[] }
  await stubActionWorld(page, state)
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/transitions', (route) =>
    fulfillJson(route, 405, { detail: 'Method internals leaked' }),
  )
  await page.goto('/action-items/action-ui5')
  await page.getByRole('button', { name: '开始整改项', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('开始整改项未被服务器接受')
  await expect(page.getByText('Method internals leaked')).toHaveCount(0)
})
