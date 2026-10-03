import { expect, test, type Page, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'M4.1 User',
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

function caseResponse(caseId: string) {
  return {
    id: caseId,
    organization_id: user.organization_id,
    plan_id: null,
    scenario_key: 'compliance_review',
    scenario_version: 1,
    title: 'M4.1 Compliance Case',
    lifecycle: 'in_progress',
    planned_start_at: null,
    planned_end_at: null,
    started_at: '2026-08-29T00:00:00Z',
    fieldwork_completed_at: null,
    closed_at: null,
    scenario_data: {
      standard_reference: 'ISO 9001:2015',
      scope_summary: 'Assembly control',
    },
    created_by: user.id,
    created_at: '2026-08-29T00:00:00Z',
  }
}

function findingResponse(
  findingId: string,
  caseId: string,
  findingType: 'observation' | 'nonconformity',
  lifecycle: 'open' | 'rectifying' | 'verifying' | 'closed' | 'voided',
) {
  return {
    id: findingId,
    organization_id: user.organization_id,
    case_id: caseId,
    title: 'M4.1 exact Scenario Finding',
    description: null,
    severity: 'medium',
    lifecycle,
    scenario_data: {
      criterion_reference: '8.5.1',
      finding_type: findingType,
    },
    raised_by: user.id,
    raised_at: '2026-08-29T01:00:00Z',
  }
}

test('409 refetch switches compliance interaction from persisted observation to nonconformity', async ({
  page,
}) => {
  await stubReadySession(page)
  const findingId = 'finding-m4-1'
  const caseId = 'case-m4-1'
  let findingType: 'observation' | 'nonconformity' = 'observation'
  let lifecycle: 'open' | 'rectifying' = 'open'
  const transitionActions: string[] = []

  await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
    fulfillJson(route, 200, findingResponse(findingId, caseId, findingType, lifecycle)),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}`, (route) =>
    fulfillJson(route, 200, caseResponse(caseId)),
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
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/transitions`,
    async (route) => {
      const payload = route.request().postDataJSON() as { action: string }
      transitionActions.push(payload.action)
      if (payload.action === 'accept_observation') {
        findingType = 'nonconformity'
        return fulfillJson(route, 409, { detail: 'Concurrent Finding transition' })
      }
      expect(payload.action).toBe('issue')
      lifecycle = 'rectifying'
      return fulfillJson(
        route,
        200,
        findingResponse(findingId, caseId, findingType, lifecycle),
      )
    },
  )

  await page.goto(`/findings/${findingId}`)

  await expect(page.getByRole('button', { name: '接受观察项' })).toBeVisible()
  await expect(page.getByRole('button', { name: '签发不符合项' })).toHaveCount(0)

  await page.getByRole('button', { name: '接受观察项' }).click()
  await page.getByRole('dialog', { name: '接受观察项' }).getByRole('button', { name: '确认接受并关闭' }).click()
  await expect(page.getByRole('alert')).toContainText('数据已变化，正在获取最新状态')
  await expect(page.getByRole('button', { name: '接受观察项' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '签发不符合项' })).toBeVisible()

  await page.getByRole('button', { name: '签发不符合项' }).click()
  await expect(page.getByText('已完成：签发不符合项')).toBeVisible()
  await expect(page.getByRole('button', { name: '签发不符合项' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '填写整改计划' })).toBeVisible()
  expect(transitionActions).toEqual(['accept_observation', 'issue'])
})
