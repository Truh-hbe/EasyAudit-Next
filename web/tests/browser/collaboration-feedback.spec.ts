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
      id: 'finding-feedback',
      organization_id: user.organization_id,
      case_id: 'case-feedback',
      title: 'Conflict Finding',
      description: null,
      severity: 'high',
      lifecycle,
      scenario_data: { issue_type: 'control_gap', project_category: 'assembly' },
      raised_by: user.id,
      raised_at: '2026-08-28T01:00:00Z',
    }),
  )
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-feedback', (route) =>
    fulfillJson(route, 200, {
      id: 'case-feedback',
      organization_id: user.organization_id,
      plan_id: null,
      scenario_key: 'process_review',
      scenario_version: 1,
      title: 'Conflict Case',
      lifecycle: 'in_progress',
      planned_start_at: null,
      planned_end_at: null,
      started_at: '2026-08-28T00:00:00Z',
      fieldwork_completed_at: null,
      closed_at: null,
      scenario_data: { area_code: 'A-01', review_type: 'routine' },
      created_by: user.id,
      created_at: '2026-08-28T00:00:00Z',
    }),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-feedback/participant-views',
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-feedback/actions',
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-feedback/submissions',
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-feedback/activities',
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-feedback/participant-candidates',
    (route) => fulfillJson(route, 200, [
      { actor_kind: 'department', actor_id: 'dept-feedback', display_name: 'Quality Department' },
    ]),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-feedback/participants',
    (route) => {
      lifecycle = 'closed'
      return fulfillJson(route, 409, { detail: 'Concurrent Finding transition' })
    },
  )

  await page.goto('/findings/finding-feedback')
  await page.getByLabel('搜索').fill('Quality')
  await page.getByRole('button', { name: '搜索候选' }).click()
  await page.getByRole('button', { name: '添加', exact: true }).click()

  await expect(page.locator('.status-pill')).toHaveText('closed')
  await expect(page.getByRole('status')).toContainText('Concurrent Finding transition')
  await expect(page.getByText('Quality Department')).toHaveCount(0)
  await expect(page.getByText('暂无参与关系。')).toBeVisible()
})
