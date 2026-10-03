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
        world.lifecycle = 'rectifying'
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
  await expect(confirm).toContainText('不能重新打开')
  expect(world.posts).toHaveLength(0) // 确认前不发请求
  await confirm.getByRole('button', { name: '确认接受并关闭' }).click()

  await expect(header(page).getByText('已关闭', { exact: true })).toBeVisible()
  await expect(page.getByText('观察项已接受并闭环。')).toBeVisible()
  await expect(page.getByRole('button', { name: '重新打开', exact: true })).toHaveCount(0)
  expect(world.posts).toEqual([{ path: 'transitions', body: { action: 'accept_observation', reason: null } }])
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
  { name: '403', status: 403, headers: {} as Record<string, string>, expected: '当前用户没有权限开始整改项：Forbidden' },
  { name: '429 with Retry-After', status: 429, headers: { 'Retry-After': '30' }, expected: '30 秒后手动重试' },
  { name: '503 with Retry-After', status: 503, headers: { 'Retry-After': '12' }, expected: '12 秒后手动重试' },
  { name: '409', status: 409, headers: {} as Record<string, string>, expected: '数据已变化，正在获取最新状态' },
]

for (const failure of failureCases) {
  test(`write failure ${failure.name} is explained and never replayed`, async ({ page }) => {
    const state = { lifecycle: 'todo', posts: [] as unknown[] }
    await stubActionWorld(page, state)
    let attempts = 0
    await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/transitions', (route) => {
      attempts += 1
      return fulfillJson(route, failure.status, { detail: 'Forbidden' }, failure.headers)
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

test('assignee drawer maps 422 detail without field names to an alert and keeps the dialog open', async ({ page }) => {
  const state = { lifecycle: 'todo', posts: [] as unknown[] }
  await stubActionWorld(page, state)
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/assignee-candidates', (route) =>
    fulfillJson(route, 200, [{ actor_kind: 'user', actor_id: 'cand', display_name: 'Candidate User' }]),
  )
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ui5/assignees', (route) =>
    fulfillJson(route, 422, { detail: 'Assignee not eligible' }),
  )
  await page.goto('/action-items/action-ui5')
  const drawer = await openAssignDrawer(page, '添加执行人', '添加执行人')
  await pickCandidate(drawer, '执行人', 'Candidate', 'Candidate User')
  await drawer.getByRole('button', { name: '添加执行人' }).click()
  await expect(drawer.getByRole('alert')).toContainText('Assignee not eligible')
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
