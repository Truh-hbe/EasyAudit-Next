import { expect, test, type Page, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'State User',
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
    title: 'State Case',
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

function finding(id: string, caseId: string, lifecycle = 'open') {
  return {
    id,
    organization_id: user.organization_id,
    case_id: caseId,
    title: 'State Finding',
    description: null,
    severity: 'medium',
    lifecycle,
    scenario_data: { issue_type: 'control_gap', project_category: 'assembly' },
    raised_by: user.id,
    raised_at: '2026-08-28T01:00:00Z',
  }
}

function action(id: string, findingId: string, lifecycle: string) {
  return {
    id,
    organization_id: user.organization_id,
    finding_id: findingId,
    title: `Action ${lifecycle}`,
    lifecycle,
    due_at: '2026-08-30T04:30:00Z',
    completed_at: lifecycle === 'done' ? '2026-08-29T02:00:00Z' : null,
  }
}

async function stubFindingBase(page: Page, findingId: string, caseId: string) {
  await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
    fulfillJson(route, 200, finding(findingId, caseId)),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}`, (route) =>
    fulfillJson(route, 200, reviewCase(caseId)),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/participant-views`,
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/actions`,
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/submissions`,
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/activities`,
    (route) => fulfillJson(route, 200, []),
  )
}

test('participant candidate lookup exposes loading, no-results, error and selection without granting authority', async ({ page }) => {
  await stubReadySession(page)
  await stubFindingBase(page, 'finding-candidates', 'case-candidates')

  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-candidates/participant-candidates',
    async (route) => {
      const query = new URL(route.request().url()).searchParams.get('q')
      if (query === 'Slow') {
        await new Promise((resolve) => setTimeout(resolve, 250))
        return fulfillJson(route, 200, [])
      }
      if (query === 'None') return fulfillJson(route, 200, [])
      if (query === 'Boom') return fulfillJson(route, 500, { detail: 'candidate lookup failed' })
      return fulfillJson(route, 200, [
        { actor_kind: 'department', actor_id: 'dept-state', display_name: 'Quality Department' },
      ])
    },
  )
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-candidates/participants',
    (route) => fulfillJson(route, 403, { detail: 'participant authority changed' }),
  )

  await page.goto('/findings/finding-candidates')
  const search = page.getByLabel('搜索')

  await search.fill('Slow')
  await page.getByRole('button', { name: '搜索候选' }).click()
  await expect(page.getByText('正在查询可选人员…')).toBeVisible()
  await expect(page.getByText('没有匹配候选。')).toBeVisible()

  await search.fill('None')
  await page.getByRole('button', { name: '搜索候选' }).click()
  await expect(page.getByText('没有匹配候选。')).toBeVisible()

  await search.fill('Boom')
  await page.getByRole('button', { name: '搜索候选' }).click()
  await expect(page.getByRole('alert')).toContainText('candidate lookup failed')

  await search.fill('Quality')
  await page.getByRole('button', { name: '搜索候选' }).click()
  await expect(page.getByText('Quality Department')).toBeVisible()
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('participant authority changed')
  await expect(page.getByText('暂无参与关系。')).toBeVisible()
})

test('Action detail presents all frozen lifecycles and formats due time without inventing overdue state', async ({ page }) => {
  await stubReadySession(page)
  let lifecycle = 'todo'
  const actionId = 'action-states'
  const findingId = 'finding-states'
  const caseId = 'case-states'

  await page.route((url) => url.pathname === `/api/v1/action-items/${actionId}`, (route) =>
    fulfillJson(route, 200, action(actionId, findingId, lifecycle)),
  )
  await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
    fulfillJson(route, 200, finding(findingId, caseId, 'rectifying')),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}`, (route) =>
    fulfillJson(route, 200, reviewCase(caseId)),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/action-items/${actionId}/assignee-views`,
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/action-items/${actionId}/evidences`,
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/action-items/${actionId}/activities`,
    (route) => fulfillJson(route, 200, []),
  )

  await page.goto(`/action-items/${actionId}`)
  await expect(page.getByRole('article').locator('header').getByText('待开始', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '开始整改项', exact: true })).toBeVisible()
  await expect(page.getByText(/2026/).first()).toBeVisible()
  await expect(page.getByText(/overdue/i)).toHaveCount(0)

  lifecycle = 'in_progress'
  await page.reload()
  await expect(page.getByRole('article').locator('header').getByText('执行中', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '完成整改项', exact: true })).toBeVisible()

  lifecycle = 'done'
  await page.reload()
  await expect(page.getByRole('article').locator('header').getByText('已完成', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '重新打开整改项', exact: true })).toBeVisible()

  lifecycle = 'cancelled'
  await page.reload()
  await expect(page.getByRole('article').locator('header').getByText('已取消', { exact: true })).toBeVisible()
  await expect(page.getByText('当前整改项已取消，没有可执行的操作。')).toBeVisible()
  await expect(page.getByRole('button', { name: '通过验证' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '驳回验证' })).toHaveCount(0)
})
