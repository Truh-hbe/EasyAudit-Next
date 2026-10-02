import { expect, test, type Page, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'Conflict User',
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

test('Finding participant 409 remains visible after authoritative terminal refetch', async ({ page }) => {
  await stubReadySession(page)
  let lifecycle = 'open'

  await page.route((url) => url.pathname === '/api/v1/findings/finding-feedback', (route) =>
    fulfillJson(route, 200, {
      id: 'finding-feedback', organization_id: user.organization_id, case_id: 'case-feedback',
      title: 'Conflict Finding', description: null, severity: 'high', lifecycle,
      scenario_data: { issue_type: 'control_gap', project_category: 'assembly' },
      raised_by: user.id, raised_at: '2026-08-28T01:00:00Z',
    }),
  )
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-feedback', (route) =>
    fulfillJson(route, 200, {
      id: 'case-feedback', organization_id: user.organization_id, plan_id: null,
      scenario_key: 'process_review', scenario_version: 1, title: 'Conflict Case', lifecycle: 'in_progress',
      planned_start_at: null, planned_end_at: null, started_at: '2026-08-28T00:00:00Z',
      fieldwork_completed_at: null, closed_at: null,
      scenario_data: { area_code: 'A-01', review_type: 'routine' },
      created_by: user.id, created_at: '2026-08-28T00:00:00Z',
    }),
  )
  await page.route((url) => url.pathname === '/api/v1/findings/finding-feedback/participant-views', (route) => fulfillJson(route, 200, []))
  await page.route((url) => url.pathname === '/api/v1/findings/finding-feedback/actions', (route) => fulfillJson(route, 200, []))
  await page.route((url) => url.pathname === '/api/v1/findings/finding-feedback/submissions', (route) => fulfillJson(route, 200, []))
  await page.route((url) => url.pathname === '/api/v1/findings/finding-feedback/activities', (route) => fulfillJson(route, 200, []))
  await page.route((url) => url.pathname === '/api/v1/findings/finding-feedback/participant-candidates', (route) =>
    fulfillJson(route, 200, [{ actor_kind: 'department', actor_id: 'dept-feedback', display_name: 'Quality Department' }]),
  )
  await page.route((url) => url.pathname === '/api/v1/findings/finding-feedback/participants', (route) => {
    lifecycle = 'closed'
    return fulfillJson(route, 409, { detail: 'Concurrent Finding transition' })
  })

  await page.goto('/findings/finding-feedback')
  await page.getByLabel('搜索').fill('Quality')
  await page.getByRole('button', { name: '搜索候选' }).click()
  await page.getByRole('button', { name: '添加', exact: true }).click()

  await expect(page.getByRole('article').locator('header').getByText('已关闭', { exact: true })).toBeVisible()
  await expect(page.getByRole('status')).toContainText('Concurrent Finding transition')
  await expect(page.getByText('Quality Department')).toHaveCount(0)
  await expect(page.getByText('暂无参与关系。')).toBeVisible()
})

test('Action command feedback is retained for refetch but cleared when the route Action changes', async ({ page }) => {
  await stubReadySession(page)

  const action = (id: string, findingId: string, title: string) => ({
    id, organization_id: user.organization_id, finding_id: findingId, title,
    lifecycle: 'todo', due_at: null, completed_at: null,
  })
  const finding = (id: string, caseId: string, title: string) => ({
    id, organization_id: user.organization_id, case_id: caseId, title,
    description: null, severity: 'medium', lifecycle: 'rectifying',
    scenario_data: { issue_type: 'control_gap', project_category: 'assembly' },
    raised_by: user.id, raised_at: '2026-08-28T01:00:00Z',
  })
  const reviewCase = (id: string) => ({
    id, organization_id: user.organization_id, plan_id: null,
    scenario_key: 'process_review', scenario_version: 1, title: `Case ${id}`, lifecycle: 'in_progress',
    planned_start_at: null, planned_end_at: null, started_at: '2026-08-28T00:00:00Z',
    fieldwork_completed_at: null, closed_at: null,
    scenario_data: { area_code: 'A-01', review_type: 'routine' },
    created_by: user.id, created_at: '2026-08-28T00:00:00Z',
  })

  for (const suffix of ['a', 'b']) {
    const actionId = `action-${suffix}`
    const findingId = `finding-${suffix}`
    const caseId = `case-${suffix}`
    await page.route((url) => url.pathname === `/api/v1/action-items/${actionId}`, (route) =>
      fulfillJson(route, 200, action(actionId, findingId, `Action ${suffix.toUpperCase()}`)),
    )
    await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
      fulfillJson(route, 200, finding(findingId, caseId, `Finding ${suffix.toUpperCase()}`)),
    )
    await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}`, (route) => fulfillJson(route, 200, reviewCase(caseId)))
    await page.route((url) => url.pathname === `/api/v1/action-items/${actionId}/assignee-views`, (route) => fulfillJson(route, 200, []))
    await page.route((url) => url.pathname === `/api/v1/action-items/${actionId}/evidences`, (route) => fulfillJson(route, 200, []))
    await page.route((url) => url.pathname === `/api/v1/action-items/${actionId}/activities`, (route) => fulfillJson(route, 200, []))
  }
  await page.route((url) => url.pathname === '/api/v1/action-items/action-a/transitions', (route) =>
    fulfillJson(route, 409, { detail: 'Action A stale transition' }),
  )

  await page.goto('/action-items/action-a')
  await page.getByRole('button', { name: '开始整改项', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Action A stale transition')
  await expect(page.getByRole('heading', { name: 'Action A', exact: true })).toBeVisible()

  await page.evaluate(
    "history.pushState({}, '', '/action-items/action-b'); dispatchEvent(new PopStateEvent('popstate'))",
  )

  await expect(page.getByRole('heading', { name: 'Action B', exact: true })).toBeVisible()
  await expect(page.getByRole('status')).toHaveCount(0)
})
