import { expect, test, type Page, type Route } from '@playwright/test'

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

test('Finding route change clears drafts and ignores a late candidate search from the previous Finding', async ({ page }) => {
  await stubReadySession(page)

  for (const suffix of ['a', 'b']) {
    const findingId = `finding-route-${suffix}`
    const caseId = `case-route-${suffix}`
    await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
      fulfillJson(route, 200, finding(findingId, caseId)),
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
  await page.getByLabel('搜索').fill('Late')
  await page.getByLabel('标题').fill('Draft Action A')
  await page.getByLabel('根本原因').fill('Root cause A')
  await page.getByLabel('整改完成说明').fill('Completion A')
  await page.getByRole('button', { name: '搜索候选' }).click()
  await expect(page.getByText('正在查询可选人员…')).toBeVisible()

  await switchRoute(page, '/findings/finding-route-b')
  await expect(page.getByRole('heading', { name: 'Route Finding finding-route-b' })).toBeVisible()
  await expect(page.getByLabel('搜索')).toHaveValue('')
  await expect(page.getByLabel('标题')).toHaveValue('')
  await expect(page.getByLabel('根本原因')).toHaveValue('')
  await expect(page.getByLabel('整改完成说明')).toHaveValue('')

  await new Promise((resolve) => setTimeout(resolve, 350))
  await expect(page.getByText('Late Candidate From A')).toHaveCount(0)
})

test('Action route change clears drafts and ignores a late mutation result from the previous Action', async ({ page }) => {
  await stubReadySession(page)

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
  await page.getByLabel('搜索').fill('Candidate A')
  await page.getByLabel('取消原因').fill('Reason A')
  await page.getByRole('button', { name: '开始整改项', exact: true }).click()

  await switchRoute(page, '/action-items/action-route-b')
  await expect(page.getByRole('heading', { name: 'Route Action action-route-b' })).toBeVisible()
  await expect(page.getByLabel('搜索')).toHaveValue('')
  await expect(page.getByLabel('取消原因')).toHaveValue('')

  await new Promise((resolve) => setTimeout(resolve, 350))
  await expect(page.getByRole('status')).toHaveCount(0)
  await expect(page.getByRole('article').locator('header').getByText('待开始', { exact: true })).toBeVisible()
})
