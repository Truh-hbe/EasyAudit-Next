import { expect, test, type Page, type Route } from '@playwright/test'

import { openAssignDrawer, searchCandidate } from './assignmentDrawer.js'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'Route Isolation User',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
}

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function stubReadySession(page: Page) {
  await page.route((url) => url.pathname === '/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...user, must_change_password: false }),
  )
}

function reviewCase(id: string) {
  return {
    id,
    organization_id: user.organization_id,
    plan_id: null,
    scenario_key: 'process_review',
    scenario_version: 1,
    title: `Route Case ${id}`,
    lifecycle: 'in_progress',
    planned_start_at: null,
    planned_end_at: null,
    started_at: '2026-08-28T00:00:00Z',
    fieldwork_completed_at: null,
    closed_at: null,
    scenario_data: { area_code: 'A-01', review_type: 'routine' },
    created_by: user.id,
    created_at: '2026-08-28T00:00:00Z',
  }
}

function finding(id: string, caseId: string, lifecycle = 'rectifying') {
  return {
    id,
    organization_id: user.organization_id,
    case_id: caseId,
    title: `Route Finding ${id}`,
    description: null,
    severity: 'high',
    lifecycle,
    scenario_data: { issue_type: 'control_gap', project_category: 'assembly' },
    raised_by: user.id,
    raised_at: '2026-08-28T01:00:00Z',
  }
}

function action(id: string, findingId: string) {
  return {
    id,
    organization_id: user.organization_id,
    finding_id: findingId,
    title: `Route Action ${id}`,
    lifecycle: 'todo',
    due_at: null,
    completed_at: null,
  }
}

async function switchRoute(page: Page, path: string) {
  await page.evaluate(
    `history.pushState({}, '', ${JSON.stringify(path)}); dispatchEvent(new PopStateEvent('popstate'))`,
  )
}

async function stubFindingRoutes(page: Page, lifecycle: string) {
  for (const suffix of ['a', 'b']) {
    const findingId = `finding-route-${suffix}`
    const caseId = `case-route-${suffix}`
    await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
      fulfillJson(route, 200, finding(findingId, caseId, lifecycle)),
    )
    await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}`, (route) =>
      fulfillJson(route, 200, reviewCase(caseId)),
    )
    for (const child of ['participant-views', 'actions', 'submissions', 'activities']) {
      await page.route((url) => url.pathname === `/api/v1/findings/${findingId}/${child}`, (route) =>
        fulfillJson(route, 200, []),
      )
    }
  }
}

test('Finding route change clears the participant search draft and ignores a late candidate search from the previous Finding', async ({ page }) => {
  await stubReadySession(page)
  await stubFindingRoutes(page, 'rectifying')

  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-route-a/participant-candidates',
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 300))
      return fulfillJson(route, 200, [
        { actor_kind: 'department', actor_id: 'late-dept', display_name: 'Late Candidate From A' },
      ])
    },
  )

  await page.goto('/findings/finding-route-a')
  const drawer = await openAssignDrawer(page, '添加参与人', '添加参与人')
  await searchCandidate(drawer, '参与人', 'Late')
  await expect(page.getByText('正在查询可选人员…')).toBeVisible()

  await switchRoute(page, '/findings/finding-route-b')
  await expect(page.getByRole('heading', { name: 'Route Finding finding-route-b' })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)

  await new Promise((resolve) => setTimeout(resolve, 350))
  await expect(page.getByText('Late Candidate From A')).toHaveCount(0)
  const reopened = await openAssignDrawer(page, '添加参与人', '添加参与人')
  await expect(reopened.getByRole('combobox', { name: '参与人' })).toHaveValue('')
  await expect(page.getByText('Late Candidate From A')).toHaveCount(0)
})

const findingDrafts = [
  { lifecycle: 'rectifying', opener: '新建整改项', dialog: '新建整改项', field: '标题', draft: 'Draft Action A' },
  { lifecycle: 'rectifying', opener: '填写整改计划', dialog: '整改计划', field: '根本原因', draft: 'Root cause A' },
  { lifecycle: 'rectifying', opener: '提交整改完成', dialog: '整改完成', field: '整改完成说明', draft: 'Completion A' },
  { lifecycle: 'verifying', opener: '驳回验证', dialog: '驳回验证', field: '驳回原因', draft: 'Reject reason A' },
  { lifecycle: 'open', opener: '作废发现项', dialog: '作废发现项', field: '作废原因', draft: 'Void reason A' },
  { lifecycle: 'closed', opener: '重新打开', dialog: '重新打开发现项', field: '重新打开原因', draft: 'Reopen reason A' },
]

for (const item of findingDrafts) {
  test(`Finding route change discards the "${item.field}" draft: reopening the dialog on the next Finding is empty`, async ({ page }) => {
    await stubReadySession(page)
    await stubFindingRoutes(page, item.lifecycle)

    await page.goto('/findings/finding-route-a')
    await page.getByRole('button', { name: item.opener, exact: true }).click()
    const dialogA = page.getByRole('dialog', { name: item.dialog })
    await dialogA.getByLabel(item.field).fill(item.draft)
    await expect(dialogA.getByLabel(item.field)).toHaveValue(item.draft)

    await switchRoute(page, '/findings/finding-route-b')
    await expect(page.getByRole('heading', { name: 'Route Finding finding-route-b' })).toBeVisible()
    await expect(page.getByRole('dialog')).toHaveCount(0)

    await page.getByRole('button', { name: item.opener, exact: true }).click()
    await expect(page.getByRole('dialog', { name: item.dialog }).getByLabel(item.field)).toHaveValue('')
  })
}

async function stubActionRoutes(page: Page) {
  for (const suffix of ['a', 'b']) {
    const actionId = `action-route-${suffix}`
    const findingId = `finding-action-route-${suffix}`
    const caseId = `case-action-route-${suffix}`
    await page.route((url) => url.pathname === `/api/v1/action-items/${actionId}`, (route) =>
      fulfillJson(route, 200, action(actionId, findingId)),
    )
    await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
      fulfillJson(route, 200, finding(findingId, caseId)),
    )
    await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}`, (route) =>
      fulfillJson(route, 200, reviewCase(caseId)),
    )
    for (const child of ['assignee-views', 'evidences', 'activities']) {
      await page.route((url) => url.pathname === `/api/v1/action-items/${actionId}/${child}`, (route) =>
        fulfillJson(route, 200, []),
      )
    }
  }
}

test('Action route change discards the cancel-reason and assignee-search drafts', async ({ page }) => {
  await stubReadySession(page)
  await stubActionRoutes(page)

  await page.goto('/action-items/action-route-a')
  await page.getByRole('button', { name: '取消整改项' }).click()
  const cancelA = page.getByRole('dialog', { name: '取消整改项' })
  await cancelA.getByLabel('取消原因').fill('Reason A')
  await switchRoute(page, '/action-items/action-route-b')
  await expect(page.getByRole('heading', { name: 'Route Action action-route-b' })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: '取消整改项' }).click()
  await expect(page.getByRole('dialog', { name: '取消整改项' }).getByLabel('取消原因')).toHaveValue('')
  await page.getByRole('dialog', { name: '取消整改项' }).getByRole('button', { name: /^取\s*消$/ }).click()

  await page.goto('/action-items/action-route-a')
  const assignA = await openAssignDrawer(page, '添加执行人', '添加执行人')
  await searchCandidate(assignA, '执行人', 'Candidate A')
  await switchRoute(page, '/action-items/action-route-b')
  await expect(page.getByRole('heading', { name: 'Route Action action-route-b' })).toBeVisible()
  const assignB = await openAssignDrawer(page, '添加执行人', '添加执行人')
  await expect(assignB.getByRole('combobox', { name: '执行人' })).toHaveValue('')
})

test('Action route change ignores a late mutation result from the previous Action', async ({ page }) => {
  await stubReadySession(page)
  await stubActionRoutes(page)

  await page.route(
    (url) => url.pathname === '/api/v1/action-items/action-route-a/transitions',
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 300))
      return fulfillJson(route, 200, {
        ...action('action-route-a', 'finding-action-route-a'),
        lifecycle: 'in_progress',
      })
    },
  )

  await page.goto('/action-items/action-route-a')
  await page.getByRole('button', { name: '开始整改项', exact: true }).click()

  await switchRoute(page, '/action-items/action-route-b')
  await expect(page.getByRole('heading', { name: 'Route Action action-route-b' })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)

  await new Promise((resolve) => setTimeout(resolve, 350))
  await expect(page.getByText('已完成：开始整改项')).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByRole('article').locator('header').getByText('待开始', { exact: true })).toBeVisible()
})

test('a confirmation left open on Finding A is destroyed on route change and never writes to A or B', async ({ page }) => {
  await stubReadySession(page)
  for (const suffix of ['a', 'b']) {
    const findingId = `finding-route-${suffix}`
    await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
      fulfillJson(route, 200, {
        ...finding(findingId, `case-route-${suffix}`, 'open'),
        scenario_data: { criterion_reference: '8.5.1', finding_type: 'observation' },
      }),
    )
    await page.route((url) => url.pathname === `/api/v1/review-cases/case-route-${suffix}`, (route) =>
      fulfillJson(route, 200, { ...reviewCase(`case-route-${suffix}`), scenario_key: 'compliance_review', scenario_data: { standard_reference: 'S', scope_summary: 'X' } }),
    )
    for (const child of ['participant-views', 'actions', 'submissions', 'activities']) {
      await page.route((url) => url.pathname === `/api/v1/findings/${findingId}/${child}`, (route) =>
        fulfillJson(route, 200, []),
      )
    }
  }
  const writes: string[] = []
  await page.route((url) => url.pathname.endsWith('/transitions'), (route) => {
    writes.push(new URL(route.request().url()).pathname)
    return fulfillJson(route, 200, finding('x', 'y', 'closed'))
  })

  await page.goto('/findings/finding-route-a')
  await page.getByRole('button', { name: '接受观察项' }).click()
  await expect(page.getByRole('dialog', { name: '接受观察项' })).toBeVisible()

  await switchRoute(page, '/findings/finding-route-b')
  await expect(page.getByRole('heading', { name: 'Route Finding finding-route-b' })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.waitForTimeout(300)
  expect(writes).toEqual([])
})
