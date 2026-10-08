import { expect, test, type Page, type Route } from '@playwright/test'

import { openAssignDrawer, pickCandidate } from './assignmentDrawer.js'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'B5 Owner',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
}

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

interface World {
  action: string
  finding: string
  posts: { new_executor_id: string; reason: string }[]
  reads: number
  outcome: { status: number; detail: string; rule?: Record<string, unknown> } | null
}

function actionResponse(lifecycle: string) {
  return {
    id: 'action-b5',
    organization_id: user.organization_id,
    finding_id: 'finding-b5',
    title: 'B5 Action',
    lifecycle,
    due_at: null,
    completed_at: lifecycle === 'done' ? '2026-10-06T00:00:00Z' : null,
  }
}

// 有状态 stub：转交并重开成功后整改项回到执行中，页面只能通过刷新看到。
async function stubWorld(page: Page, world: World) {
  await page.route((url) => url.pathname === '/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...user, must_change_password: false }),
  )
  await page.route((url) => url.pathname === '/api/v1/action-items/action-b5', (route) => {
    world.reads += 1
    return fulfillJson(route, 200, actionResponse(world.action))
  })
  await page.route((url) => url.pathname === '/api/v1/findings/finding-b5', (route) =>
    fulfillJson(route, 200, {
      id: 'finding-b5',
      organization_id: user.organization_id,
      case_id: 'case-b5',
      title: 'B5 Finding',
      description: null,
      severity: 'high',
      lifecycle: world.finding,
      scenario_data: { issue_type: 'control_gap', project_category: 'assembly' },
      raised_by: user.id,
      raised_at: '2026-10-01T00:00:00Z',
    }),
  )
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-b5', (route) =>
    fulfillJson(route, 200, {
      id: 'case-b5',
      organization_id: user.organization_id,
      plan_id: null,
      scenario_key: 'process_review',
      scenario_version: 1,
      title: 'B5 Case',
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
  await page.route((url) => url.pathname === '/api/v1/action-items/action-b5/assignee-views', (route) =>
    fulfillJson(route, 200, [
      {
        action_item_id: 'action-b5',
        actor_kind: 'user',
        actor_id: 'old-primary',
        role: 'primary',
        assigned_at: '2026-10-01T00:00:00Z',
        display_name: 'Old Primary',
      },
    ]),
  )
  for (const child of ['activities', 'evidences']) {
    await page.route((url) => url.pathname === `/api/v1/action-items/action-b5/${child}`, (route) =>
      fulfillJson(route, 200, []),
    )
  }
  await page.route((url) => url.pathname === '/api/v1/action-items/action-b5/transfer-candidates', (route) =>
    fulfillJson(route, 200, [{ actor_kind: 'user', actor_id: 'new-executor', display_name: 'New Executor' }]),
  )
  await page.route((url) => url.pathname === '/api/v1/action-items/action-b5/transfer-and-reopen', (route) => {
    world.posts.push(route.request().postDataJSON() as { new_executor_id: string; reason: string })
    if (world.outcome !== null) return fulfillJson(route, world.outcome.status, { detail: world.outcome.detail, ...world.outcome.rule })
    world.action = 'in_progress'
    return fulfillJson(route, 200, actionResponse('in_progress'))
  })
}

const fresh = (overrides: Partial<World> = {}): World => ({
  action: 'done',
  finding: 'rectifying',
  posts: [],
  reads: 0,
  outcome: null,
  ...overrides,
})

const header = (page: Page) => page.getByRole('article').locator('header')
const opener = (page: Page) => page.getByRole('button', { name: '转交并重开', exact: true })

test('a done Action of a rectifying Finding is transferred with a required reason and reopens, sending exactly one request', async ({ page }) => {
  const world = fresh()
  await stubWorld(page, world)
  await page.goto('/action-items/action-b5')
  await expect(header(page).getByText('已完成', { exact: true })).toBeVisible()

  const drawer = await openAssignDrawer(page, '转交并重开', '转交并重开整改项')
  await pickCandidate(drawer, '新执行人', 'New', 'New Executor')
  // 缺少原因：表单拦截，不发请求。
  await drawer.getByRole('button', { name: '确认转交并重开' }).click()
  await expect(drawer.getByText('请填写转交原因')).toBeVisible()
  expect(world.posts).toEqual([])

  await drawer.getByRole('textbox', { name: '转交原因' }).fill('原执行人已离职')
  await drawer.getByRole('button', { name: '确认转交并重开' }).click()
  await expect(header(page).getByText('执行中', { exact: true })).toBeVisible()
  expect(world.posts).toEqual([{ new_executor_id: 'new-executor', reason: '原执行人已离职' }])
  await expect(drawer).toHaveCount(0)
  await expect(opener(page)).toHaveCount(0)
})

for (const [name, overrides] of [
  ['an in-progress Action', { action: 'in_progress' }],
  ['a todo Action', { action: 'todo' }],
  ['a done Action whose Finding is not rectifying', { finding: 'verifying' }],
] as const) {
  test(`${name} offers no transfer entry (state only, no derived permission)`, async ({ page }) => {
    await stubWorld(page, fresh(overrides))
    await page.goto('/action-items/action-b5')
    await expect(page.getByRole('heading', { level: 1, name: 'B5 Action' })).toBeVisible()
    await expect(opener(page)).toHaveCount(0)
  })
}

test('a 403 shows a neutral prompt without backend detail, keeps the drawer, does not replay and re-checks the Action', async ({ page }) => {
  const world = fresh({ outcome: { status: 403, detail: 'Finding owner role required to transfer and reopen ActionItem' } })
  await stubWorld(page, world)
  await page.goto('/action-items/action-b5')
  const drawer = await openAssignDrawer(page, '转交并重开', '转交并重开整改项')
  await pickCandidate(drawer, '新执行人', 'New', 'New Executor')
  await drawer.getByRole('textbox', { name: '转交原因' }).fill('原执行人已离职')
  const readsBefore = world.reads
  await drawer.getByRole('button', { name: '确认转交并重开' }).click()
  await expect(drawer.getByRole('alert')).toContainText('当前账号没有执行此操作的权限。')
  await expect(page.getByText('Finding owner role required')).toHaveCount(0)
  await expect(drawer).toBeVisible()
  expect(world.posts).toHaveLength(1)
  await expect.poll(() => world.reads).toBeGreaterThan(readsBefore)
  // 失败后已选执行人作废，原因文本保留。
  await expect(drawer.getByRole('textbox', { name: '转交原因' })).toHaveValue('原执行人已离职')
})

test('a 409 gets the refresh prompt, refetches the Action and is never replayed', async ({ page }) => {
  const world = fresh({ outcome: { status: 409, detail: 'Concurrent ActionItem transition' } })
  await stubWorld(page, world)
  await page.goto('/action-items/action-b5')
  const drawer = await openAssignDrawer(page, '转交并重开', '转交并重开整改项')
  await pickCandidate(drawer, '新执行人', 'New', 'New Executor')
  await drawer.getByRole('textbox', { name: '转交原因' }).fill('原执行人已离职')
  const readsBefore = world.reads
  await drawer.getByRole('button', { name: '确认转交并重开' }).click()
  await expect(drawer.getByRole('alert')).toContainText('数据已变化，正在获取最新状态')
  await expect.poll(() => world.reads).toBeGreaterThan(readsBefore)
  await page.waitForTimeout(500)
  expect(world.posts).toHaveLength(1)
})

test('a 422 about the reason is shown on the reason field and keeps the drawer open', async ({ page }) => {
  const world = fresh({
    outcome: {
      status: 422,
      detail: 'Transferring and reopening an ActionItem requires a reason',
      rule: { code: 'request.invalid', params: {}, errors: [{ field: 'reason', code: 'required', params: {} }] },
    },
  })
  await stubWorld(page, world)
  await page.goto('/action-items/action-b5')
  const drawer = await openAssignDrawer(page, '转交并重开', '转交并重开整改项')
  await pickCandidate(drawer, '新执行人', 'New', 'New Executor')
  await drawer.getByRole('textbox', { name: '转交原因' }).fill('x')
  await drawer.getByRole('button', { name: '确认转交并重开' }).click()
  await expect(drawer.locator('.field-error-text')).toContainText('请填写转交原因')
  expect(await page.getByText('requires a reason').count()).toBe(0)
  await expect(drawer.getByRole('alert')).toHaveCount(0)
  await expect(drawer).toBeVisible()
})

test('the transfer drawer is closed when the page switches to another Action', async ({ page }) => {
  const world = fresh()
  await stubWorld(page, world)
  await page.route((url) => url.pathname === '/api/v1/action-items/action-b5-other', (route) =>
    fulfillJson(route, 404, { detail: 'not found' }),
  )
  await page.goto('/action-items/action-b5')
  const drawer = await openAssignDrawer(page, '转交并重开', '转交并重开整改项')
  await expect(drawer).toBeVisible()
  await page.evaluate(
    `history.pushState({}, '', '/action-items/action-b5-other'); dispatchEvent(new PopStateEvent('popstate'))`,
  )
  await expect(page.getByRole('dialog', { name: '转交并重开整改项' })).toHaveCount(0)
  expect(world.posts).toEqual([])
})

test('a 422 because an executor is still active is shown as an alert, keeps the drawer open and is not replayed', async ({ page }) => {
  const world = fresh({
    outcome: {
      status: 422,
      detail: 'ActionItem still has an active executor, who can reopen it directly',
      rule: { code: 'action.executor_still_active', params: {}, errors: [] },
    },
  })
  await stubWorld(page, world)
  await page.goto('/action-items/action-b5')
  const drawer = await openAssignDrawer(page, '转交并重开', '转交并重开整改项')
  await pickCandidate(drawer, '新执行人', 'New', 'New Executor')
  await drawer.getByRole('textbox', { name: '转交原因' }).fill('原执行人已离职')
  await drawer.getByRole('button', { name: '确认转交并重开' }).click()
  await expect(drawer.getByRole('alert')).toContainText('原执行人仍可操作，可以直接重新打开，无需转交。')
  expect(await page.getByText('still has an active executor').count()).toBe(0)
  await expect(drawer).toBeVisible()
  await page.waitForTimeout(500)
  expect(world.posts).toHaveLength(1)
})
