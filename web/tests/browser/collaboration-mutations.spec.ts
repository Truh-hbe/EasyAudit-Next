import { expect, test, type Page, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'Mutation User',
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

function caseResponse(id: string) {
  return {
    id,
    organization_id: user.organization_id,
    plan_id: null,
    scenario_key: 'process_review',
    scenario_version: 1,
    title: 'Mutation Case',
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

function findingResponse(id: string, caseId: string, lifecycle: string) {
  return {
    id,
    organization_id: user.organization_id,
    case_id: caseId,
    title: 'Mutation Finding',
    description: null,
    severity: 'high',
    lifecycle,
    scenario_data: { issue_type: 'control_gap', project_category: 'assembly' },
    raised_by: user.id,
    raised_at: '2026-08-28T01:00:00Z',
  }
}

function actionResponse(id: string, findingId: string, lifecycle: string, title = 'Mutation Action') {
  return {
    id,
    organization_id: user.organization_id,
    finding_id: findingId,
    title,
    lifecycle,
    due_at: null,
    completed_at: lifecycle === 'done' ? '2026-08-28T02:00:00Z' : null,
  }
}

function submissionResponse(
  id: string,
  caseId: string,
  findingId: string,
  purpose: 'rectification' | 'verification',
  payload: Record<string, unknown>,
) {
  return {
    id,
    organization_id: user.organization_id,
    case_id: caseId,
    finding_id: findingId,
    purpose,
    submitted_by: user.id,
    submitted_at: '2026-08-28T03:00:00Z',
    payload,
  }
}

async function stubFindingContext(
  page: Page,
  findingId: string,
  caseId: string,
  getLifecycle: () => string,
  getActions: () => unknown[],
  getSubmissions: () => unknown[],
) {
  await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
    fulfillJson(route, 200, findingResponse(findingId, caseId, getLifecycle())),
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
    (route) => {
      if (route.request().method() === 'GET') return fulfillJson(route, 200, getActions())
      return route.fallback()
    },
  )
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/submissions`,
    (route) => fulfillJson(route, 200, getSubmissions()),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/activities`,
    (route) => fulfillJson(route, 200, []),
  )
}

test('Action creation refuses fake local state then refreshes persisted server Action on success', async ({ page }) => {
  await stubReadySession(page)
  const findingId = 'finding-create-action'
  const caseId = 'case-create-action'
  const actions: unknown[] = []
  let allowCreate = false

  await stubFindingContext(page, findingId, caseId, () => 'rectifying', () => actions, () => [])
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/actions`,
    (route) => {
      if (route.request().method() === 'GET') return fulfillJson(route, 200, actions)
      if (!allowCreate) return fulfillJson(route, 422, { detail: 'Finding lifecycle changed' })
      const persisted = actionResponse('action-persisted', findingId, 'todo', 'Server persisted Action')
      actions.push(persisted)
      return fulfillJson(route, 201, persisted)
    },
  )

  await page.goto(`/findings/${findingId}`)
  await page.getByLabel('标题').fill('Client draft title')
  await page.getByRole('button', { name: '创建', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Finding lifecycle changed')
  await expect(page.getByText('Client draft title')).toHaveCount(0)
  await expect(page.getByText('暂无 Action Item。')).toBeVisible()

  allowCreate = true
  await page.getByRole('button', { name: '创建', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Server persisted Action' })).toBeVisible()
  await expect(page.getByText('Client draft title')).toHaveCount(0)
})

test('assignee refusal never creates a local assignment and success refreshes persisted assignee truth', async ({ page }) => {
  await stubReadySession(page)
  const actionId = 'action-assignee'
  const findingId = 'finding-assignee'
  const caseId = 'case-assignee'
  let allowAssign = false
  const assignees: unknown[] = []

  await page.route((url) => url.pathname === `/api/v1/action-items/${actionId}`, (route) =>
    fulfillJson(route, 200, actionResponse(actionId, findingId, 'todo')),
  )
  await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
    fulfillJson(route, 200, findingResponse(findingId, caseId, 'rectifying')),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}`, (route) =>
    fulfillJson(route, 200, caseResponse(caseId)),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/action-items/${actionId}/assignee-views`,
    (route) => fulfillJson(route, 200, assignees),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/action-items/${actionId}/evidences`,
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/action-items/${actionId}/activities`,
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/action-items/${actionId}/assignee-candidates`,
    (route) => fulfillJson(route, 200, [
      { actor_kind: 'user', actor_id: 'candidate-user', display_name: 'Candidate User' },
    ]),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/action-items/${actionId}/assignees`,
    (route) => {
      if (!allowAssign) return fulfillJson(route, 403, { detail: 'assignment authority changed' })
      assignees.push({
        action_item_id: actionId,
        actor_kind: 'user',
        actor_id: 'candidate-user',
        role: 'primary',
        assigned_at: '2026-08-28T04:00:00Z',
        display_name: 'Persisted Assignee',
      })
      return fulfillJson(route, 201, {
        action_item_id: actionId,
        actor_kind: 'user',
        actor_id: 'candidate-user',
        role: 'primary',
        assigned_at: '2026-08-28T04:00:00Z',
      })
    },
  )

  await page.goto(`/action-items/${actionId}`)
  await page.getByLabel('搜索').fill('Candidate')
  await page.getByRole('button', { name: '搜索候选' }).click()
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('assignment authority changed')
  await expect(page.getByText('Candidate User')).toBeVisible()
  await expect(page.getByText('Persisted Assignee')).toHaveCount(0)
  await expect(page.getByText('暂无执行人。')).toBeVisible()

  allowAssign = true
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await expect(page.getByText('Persisted Assignee')).toBeVisible()
  await expect(page.getByText('Candidate User')).toHaveCount(0)
})

test('rectification plan and completion stay server-owned, including reopened-Action completion counterexample', async ({ page }) => {
  await stubReadySession(page)
  const findingId = 'finding-rectification'
  const caseId = 'case-rectification'
  let lifecycle = 'rectifying'
  let planAllowed = false
  let completionAllowed = false
  const actions: unknown[] = [actionResponse('action-done', findingId, 'done', 'Initially done Action')]
  const submissions: unknown[] = []

  await stubFindingContext(page, findingId, caseId, () => lifecycle, () => actions, () => submissions)
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/rectification-submissions`,
    async (route) => {
      const requestBody = route.request().postDataJSON() as { action: string; payload: Record<string, unknown> }
      if (requestBody.action === 'submit_plan') {
        if (!planAllowed) return fulfillJson(route, 422, { detail: 'root_cause is required' })
        const submission = submissionResponse('submission-plan', caseId, findingId, 'rectification', requestBody.payload)
        submissions.push(submission)
        return fulfillJson(route, 201, { submission, finding: findingResponse(findingId, caseId, lifecycle) })
      }
      if (!completionAllowed) {
        actions.splice(0, actions.length, actionResponse('action-done', findingId, 'in_progress', 'Reopened by another actor'))
        return fulfillJson(route, 422, { detail: 'all non-cancelled Actions must be done' })
      }
      lifecycle = 'verifying'
      const submission = submissionResponse('submission-completion', caseId, findingId, 'rectification', requestBody.payload)
      submissions.push(submission)
      return fulfillJson(route, 201, { submission, finding: findingResponse(findingId, caseId, lifecycle) })
    },
  )

  await page.goto(`/findings/${findingId}`)
  await page.getByRole('button', { name: '提交正式计划' }).click()
  await expect(page.getByRole('status')).toContainText('root_cause is required')
  await expect(page.getByText('暂无 Finding Submission。')).toBeVisible()

  await page.getByLabel('根本原因').fill('training gap')
  planAllowed = true
  await page.getByRole('button', { name: '提交正式计划' }).click()
  await expect(page.getByText('rectification').first()).toBeVisible()
  await expect(page.locator('.status-pill')).toHaveText('rectifying')

  await page.getByLabel('整改完成说明').fill('all actions completed')
  await page.getByRole('button', { name: '提交验证' }).click()
  await expect(page.getByRole('status')).toContainText('all non-cancelled Actions must be done')
  await expect(page.locator('.status-pill')).toHaveText('rectifying')
  await expect(page.getByRole('link', { name: 'Reopened by another actor' })).toBeVisible()

  actions.splice(0, actions.length, actionResponse('action-done', findingId, 'done', 'Completed again'))
  completionAllowed = true
  await page.getByRole('button', { name: '提交验证' }).click()
  await expect(page.locator('.status-pill')).toHaveText('verifying')
  await expect(page.getByText('rectification')).toHaveCount(2)
})

test('verification refusal, reject success, and reopen validation preserve authoritative Finding state', async ({ page }) => {
  await stubReadySession(page)
  const findingId = 'finding-verification'
  const caseId = 'case-verification'
  let lifecycle = 'verifying'
  let verificationMode: 'refuse' | 'reject' = 'refuse'
  let reopenAllowed = false
  const submissions: unknown[] = []

  await stubFindingContext(page, findingId, caseId, () => lifecycle, () => [], () => submissions)
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/verification-submissions`,
    (route) => {
      const requestBody = route.request().postDataJSON() as { action: string; payload: Record<string, unknown> }
      if (verificationMode === 'refuse') return fulfillJson(route, 403, { detail: 'review authority revoked' })
      lifecycle = 'rectifying'
      const submission = submissionResponse('submission-reject', caseId, findingId, 'verification', requestBody.payload)
      submissions.push(submission)
      return fulfillJson(route, 201, { submission, finding: findingResponse(findingId, caseId, lifecycle) })
    },
  )
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/reopen`,
    (route) => {
      if (!reopenAllowed) return fulfillJson(route, 422, { detail: 'reopen reason required' })
      lifecycle = 'rectifying'
      return fulfillJson(route, 200, findingResponse(findingId, caseId, lifecycle))
    },
  )

  await page.goto(`/findings/${findingId}`)
  await page.getByRole('button', { name: 'Approve' }).click()
  await expect(page.getByRole('status')).toContainText('review authority revoked')
  await expect(page.locator('.status-pill')).toHaveText('verifying')
  await expect(page.getByText('暂无 Finding Submission。')).toBeVisible()

  verificationMode = 'reject'
  await page.getByLabel('驳回原因').fill('evidence incomplete')
  await page.getByRole('button', { name: 'Reject' }).click()
  await expect(page.locator('.status-pill')).toHaveText('rectifying')
  await expect(page.getByText('verification')).toBeVisible()

  lifecycle = 'closed'
  await page.reload()
  await page.getByRole('button', { name: '重新打开' }).click()
  await expect(page.getByRole('status')).toContainText('reopen reason required')
  await expect(page.locator('.status-pill')).toHaveText('closed')

  await page.getByLabel('重新打开原因').fill('follow-up review')
  reopenAllowed = true
  await page.getByRole('button', { name: '重新打开' }).click()
  await expect(page.locator('.status-pill')).toHaveText('rectifying')
})
