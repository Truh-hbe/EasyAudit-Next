import { expect, test, type Page, type Route } from '@playwright/test'

import { openAssignDrawer, pickCandidate } from './assignmentDrawer.js'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'Final Acceptance User',
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
    title: `Case ${id}`,
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

function finding(id: string, caseId: string, lifecycle: string, title = `Finding ${id}`) {
  return {
    id,
    organization_id: user.organization_id,
    case_id: caseId,
    title,
    description: null,
    severity: 'high',
    lifecycle,
    scenario_data: { issue_type: 'control_gap', project_category: 'assembly' },
    raised_by: user.id,
    raised_at: '2026-08-28T01:00:00Z',
  }
}

async function stubFindingChildren(
  page: Page,
  findingId: string,
  participantViews: () => unknown[] = () => [],
  submissions: () => unknown[] = () => [],
) {
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/participant-views`,
    (route) => fulfillJson(route, 200, participantViews()),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/actions`,
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/submissions`,
    (route) => fulfillJson(route, 200, submissions()),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/activities`,
    (route) => fulfillJson(route, 200, []),
  )
}

test('Finding visibility revocation replaces previously authorized content with safe unavailable state', async ({ page }) => {
  await stubReadySession(page)
  const findingId = 'finding-revoked'
  const caseId = 'case-revoked'
  let allowed = true
  let childRequestsAfterRevocation = 0

  await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
    allowed
      ? fulfillJson(route, 200, finding(findingId, caseId, 'open', 'Previously visible Finding'))
      : fulfillJson(route, 403, { detail: 'Finding visibility revoked' }),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}`, (route) => {
    if (!allowed) childRequestsAfterRevocation += 1
    return fulfillJson(route, 200, reviewCase(caseId))
  })
  for (const suffix of ['participant-views', 'actions', 'submissions', 'activities']) {
    await page.route((url) => url.pathname === `/api/v1/findings/${findingId}/${suffix}`, (route) => {
      if (!allowed) childRequestsAfterRevocation += 1
      return fulfillJson(route, 200, [])
    })
  }

  await page.goto(`/findings/${findingId}`)
  await expect(page.getByRole('heading', { name: 'Previously visible Finding' })).toBeVisible()
  await expect(page.getByText('暂无参与关系。')).toBeVisible()
  await expect(page.getByText('暂无整改项。')).toBeVisible()
  await expect(page.getByText('暂无提交记录。')).toBeVisible()
  await expect(page.getByText('暂无操作记录。')).toBeVisible()

  childRequestsAfterRevocation = 0
  allowed = false
  await page.reload()
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByText('Previously visible Finding')).toHaveCount(0)
  expect(childRequestsAfterRevocation).toBe(0)
})

test('same-org refusal and cross-org non-resolution never start Finding child reads', async ({ page }) => {
  await stubReadySession(page)
  let childRequests = 0
  for (const target of [
    { id: 'finding-unrelated', status: 403 },
    { id: 'finding-cross-org', status: 404 },
  ]) {
    await page.route((url) => url.pathname === `/api/v1/findings/${target.id}`, (route) =>
      fulfillJson(route, target.status, { detail: 'Unavailable' }),
    )
    await page.route((url) => url.pathname.startsWith(`/api/v1/findings/${target.id}/`), (route) => {
      childRequests += 1
      return fulfillJson(route, 500, { detail: 'must not be called' })
    })
    await page.goto(`/findings/${target.id}`)
    await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  }
  expect(childRequests).toBe(0)
})

test('participant success renders only the persisted relationship returned by authoritative refetch', async ({ page }) => {
  await stubReadySession(page)
  const findingId = 'finding-participant-success'
  const caseId = 'case-participant-success'
  const persistedParticipants: unknown[] = []

  await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
    fulfillJson(route, 200, finding(findingId, caseId, 'open')),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}`, (route) =>
    fulfillJson(route, 200, reviewCase(caseId)),
  )
  await stubFindingChildren(page, findingId, () => persistedParticipants)
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/participant-candidates`,
    (route) => fulfillJson(route, 200, [
      { actor_kind: 'department', actor_id: 'dept-persisted', display_name: 'Candidate Department' },
    ]),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/participants`,
    (route) => {
      persistedParticipants.push({
        finding_id: findingId,
        actor_kind: 'department',
        actor_id: 'dept-persisted',
        role_key: 'responsible_department',
        assigned_at: '2026-08-28T05:00:00Z',
        display_name: 'Persisted Department',
      })
      return fulfillJson(route, 201, {
        finding_id: findingId,
        actor_kind: 'department',
        actor_id: 'dept-persisted',
        role_key: 'responsible_department',
        assigned_at: '2026-08-28T05:00:00Z',
      })
    },
  )

  await page.goto(`/findings/${findingId}`)
  const drawer = await openAssignDrawer(page, '添加参与人', '添加参与人')
  await pickCandidate(drawer, '参与人', 'Candidate', 'Candidate Department')
  await drawer.getByRole('button', { name: '添加参与人' }).click()

  await expect(page.getByRole('list', { name: '参与方' }).getByText('Persisted Department')).toBeVisible()
  await expect(page.getByText('责任方', { exact: true })).toBeVisible()
  await expect(page.getByText('责任部门 Persisted Department')).toBeVisible() // 首屏概览同步来自刷新后的服务端数据
  await expect(page.getByText('Candidate Department')).toHaveCount(0)
})

test('verification approve success closes from server truth and refreshes persisted Submission history', async ({ page }) => {
  await stubReadySession(page)
  const findingId = 'finding-approve-success'
  const caseId = 'case-approve-success'
  let lifecycle = 'verifying'
  const submissions: unknown[] = []

  await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
    fulfillJson(route, 200, finding(findingId, caseId, lifecycle)),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}`, (route) =>
    fulfillJson(route, 200, reviewCase(caseId)),
  )
  await stubFindingChildren(page, findingId, () => [], () => submissions)
  await page.route(
    (url) => url.pathname === `/api/v1/findings/${findingId}/verification-submissions`,
    (route) => {
      lifecycle = 'closed'
      const submission = {
        id: 'submission-approved',
        organization_id: user.organization_id,
        case_id: caseId,
        finding_id: findingId,
        purpose: 'verification',
        submitted_by: user.id,
        submitted_at: '2026-08-28T06:00:00Z',
        payload: { result: 'approved' },
      }
      submissions.push(submission)
      return fulfillJson(route, 201, {
        submission,
        finding: finding(findingId, caseId, lifecycle),
      })
    },
  )

  await page.goto(`/findings/${findingId}`)
  await page.getByRole('button', { name: '通过验证' }).click()

  await expect(page.getByRole('article').locator('header').getByText('已关闭', { exact: true })).toBeVisible()
  const submissionHistory = page.locator('section[aria-labelledby="submission-history-title"]')
  await expect(submissionHistory.getByText('验证结论', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '通过验证' })).toHaveCount(0)
})

test('Finding creation 403 leaves the authorized Case list unchanged and creates no local Finding', async ({ page }) => {
  await stubReadySession(page)
  const caseId = 'case-create-forbidden'

  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}`, (route) =>
    fulfillJson(route, 200, reviewCase(caseId)),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}/members`, (route) =>
    fulfillJson(route, 200, []),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}/activities`, (route) =>
    fulfillJson(route, 200, []),
  )
  await page.route((url) => url.pathname === `/api/v1/management/review-cases/${caseId}/progress`, (route) =>
    fulfillJson(route, 404, { detail: 'Not available' }),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}/findings`, (route) =>
    route.request().method() === 'POST'
      ? fulfillJson(route, 403, { detail: 'create authority revoked' })
      : fulfillJson(route, 200, []),
  )

  await page.goto(`/review-cases/${caseId}`)
  await page.getByLabel('标题').fill('Forbidden local draft')
  await page.getByLabel('问题类型').fill('control_gap')
  await page.getByLabel('项目类别').fill('assembly')
  await page.getByRole('button', { name: '新建发现项' }).click()

  await expect(page.getByRole('alert')).toContainText('create authority revoked')
  await expect(page.getByText('暂无可见的发现项。')).toBeVisible()
  await expect(page.getByText('Forbidden local draft')).toHaveCount(0)
  await expect(page).toHaveURL(new RegExp(`/review-cases/${caseId}$`))
})
