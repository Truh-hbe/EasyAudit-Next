import { expect, test, type Page, type Route } from '@playwright/test'

import { openAssignDrawer, pickCandidate } from './assignmentDrawer.js'

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
  await page.getByRole('button', { name: '新建整改项', exact: true }).click()
  const drawer = page.getByRole('dialog', { name: '新建整改项' })
  await drawer.getByLabel('标题').fill('Client draft title')
  await drawer.getByRole('button', { name: '创建整改项' }).click()
  await expect(drawer.getByRole('alert')).toContainText('Finding lifecycle changed')
  await expect(page.getByRole('link', { name: 'Client draft title' })).toHaveCount(0)
  await expect(page.getByText('暂无整改项。')).toBeVisible()
  await expect(drawer.getByLabel('标题')).toHaveValue('Client draft title') // 失败后保留已填内容

  allowCreate = true
  await drawer.getByRole('button', { name: '创建整改项' }).click()
  await expect(page.getByRole('link', { name: 'Server persisted Action' })).toBeVisible()
  await expect(drawer).toHaveCount(0)
  await expect(page.getByText('Client draft title')).toHaveCount(0)
})

test('assignee refusal invalidates stale candidates and success refreshes persisted assignee truth', async ({ page }) => {
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
  const drawer = await openAssignDrawer(page, '添加执行人', '添加执行人')
  await pickCandidate(drawer, '执行人', 'Candidate', 'Candidate User')
  await drawer.getByRole('button', { name: '添加执行人' }).click()
  await expect(drawer.getByRole('alert')).toContainText('当前账号没有执行此操作的权限。')
  await expect(page.getByText('assignment authority changed')).toHaveCount(0)
  await expect(page.getByText('Candidate User')).toHaveCount(0) // 过期候选被清空
  await expect(page.getByText('Persisted Assignee')).toHaveCount(0)
  await expect(page.getByText('暂无执行人。')).toBeVisible()

  allowAssign = true
  await pickCandidate(drawer, '执行人', 'Candidate', 'Candidate User')
  await drawer.getByRole('button', { name: '添加执行人' }).click()
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
  await page.getByRole('button', { name: '填写整改计划' }).click()
  const planDrawer = page.getByRole('dialog', { name: '整改计划' })
  await planDrawer.getByRole('button', { name: '提交整改计划' }).click()
  await expect(planDrawer.getByText('root_cause is required')).toBeVisible() // 422 挂在字段上
  await expect(planDrawer.getByLabel('根本原因')).toBeFocused()
  await expect(page.getByText('暂无提交记录。')).toBeVisible()

  await planDrawer.getByLabel('根本原因').fill('training gap')
  planAllowed = true
  await planDrawer.getByRole('button', { name: '提交整改计划' }).click()
  const submissionHistory = page.locator('section[aria-labelledby="submission-history-title"]')
  await expect(submissionHistory.getByText('整改提交', { exact: true })).toHaveCount(1)
  await expect(page.getByRole('article').locator('header').getByText('整改中', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '提交整改完成' }).click()
  const completionDrawer = page.getByRole('dialog', { name: '整改完成' })
  await completionDrawer.getByLabel('整改完成说明').fill('all actions completed')
  await completionDrawer.getByRole('button', { name: '提交验证' }).click()
  await expect(completionDrawer.getByRole('alert')).toContainText('all non-cancelled Actions must be done')
  await expect(page.getByRole('article').locator('header').getByText('整改中', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Reopened by another actor' })).toBeVisible()
  await expect(completionDrawer.getByLabel('整改完成说明')).toHaveValue('all actions completed')

  actions.splice(0, actions.length, actionResponse('action-done', findingId, 'done', 'Completed again'))
  completionAllowed = true
  await completionDrawer.getByRole('button', { name: '提交验证' }).click()
  await expect(page.getByRole('article').locator('header').getByText('待验证', { exact: true })).toBeVisible()
  await expect(submissionHistory.getByText('整改提交', { exact: true })).toHaveCount(2)
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
  await page.getByRole('button', { name: '通过验证' }).click()
  await page.getByRole('dialog', { name: '通过验证' }).getByRole('button', { name: '确认通过' }).click()
  await expect(page.getByRole('alert')).toContainText('当前账号没有执行此操作的权限。')
  await expect(page.getByText('review authority revoked')).toHaveCount(0)
  await expect(page.getByRole('article').locator('header').getByText('待验证', { exact: true })).toBeVisible()
  await expect(page.getByText('暂无提交记录。')).toBeVisible()

  verificationMode = 'reject'
  await page.getByRole('button', { name: '驳回验证' }).click()
  const rejectDialog = page.getByRole('dialog', { name: '驳回验证' })
  await rejectDialog.getByLabel('驳回原因').fill('evidence incomplete')
  await rejectDialog.getByRole('button', { name: '确认驳回' }).click()
  await expect(page.getByRole('article').locator('header').getByText('整改中', { exact: true })).toBeVisible()
  const submissionHistory = page.locator('section[aria-labelledby="submission-history-title"]')
  await expect(submissionHistory.getByText('验证结论', { exact: true })).toBeVisible()

  lifecycle = 'closed'
  await page.reload()
  await page.getByRole('button', { name: '重新打开', exact: true }).click()
  const reopenDialog = page.getByRole('dialog', { name: '重新打开发现项' })
  await reopenDialog.getByRole('button', { name: '确认重新打开' }).click()
  await expect(reopenDialog.getByText('reopen reason required')).toBeVisible()
  await expect(page.getByRole('article').locator('header').getByText('已关闭', { exact: true })).toBeVisible()

  await reopenDialog.getByLabel('重新打开原因').fill('follow-up review')
  reopenAllowed = true
  await reopenDialog.getByRole('button', { name: '确认重新打开' }).click()
  await expect(page.getByRole('article').locator('header').getByText('整改中', { exact: true })).toBeVisible()
})

test.describe('device time zone differs from the display time zone', () => {
  test.use({ timezoneId: 'America/New_York' })

  test('a filled but non-existent Shanghai due time blocks Action creation; an empty due time still submits null', async ({ page }) => {
    await stubReadySession(page)
    const findingId = 'finding-action-invalid-due'
    const caseId = 'case-action-invalid-due'
    const createBodies: Record<string, unknown>[] = []

    await stubFindingContext(page, findingId, caseId, () => 'rectifying', () => [], () => [])
    await page.route(
      (url) => url.pathname === `/api/v1/findings/${findingId}/actions`,
      (route) => {
        if (route.request().method() === 'GET') return fulfillJson(route, 200, [])
        createBodies.push(route.request().postDataJSON() as Record<string, unknown>)
        return fulfillJson(route, 422, { detail: 'stop after capturing the request' })
      },
    )

    await page.goto(`/findings/${findingId}`)
    await page.getByRole('button', { name: '新建整改项', exact: true }).click()
    const drawer = page.getByRole('dialog', { name: '新建整改项' })
    const dueAt = drawer.getByLabel('到期时间')
    await drawer.getByLabel('标题').fill('Invalid Due Action')
    await dueAt.fill('1986/05/04 02:30')
    await dueAt.press('Enter')
    await drawer.getByLabel('标题').click() // 点到面板外，关闭日期面板
    await drawer.getByRole('button', { name: '创建整改项' }).click()
    await expect(drawer.getByText('到期时间无效：请填写存在的上海时间（Asia/Shanghai）。')).toBeVisible()
    await expect(dueAt).toHaveValue('1986/05/04 02:30')
    await expect(drawer.getByLabel('标题')).toHaveValue('Invalid Due Action')
    expect(createBodies).toHaveLength(0)

    await dueAt.fill('')
    await dueAt.press('Enter')
    await drawer.getByLabel('标题').click()
    await drawer.getByRole('button', { name: '创建整改项' }).click()
    await expect.poll(() => createBodies.length).toBe(1)
    expect(createBodies[0]).toMatchObject({ title: 'Invalid Due Action', due_at: null })
  })

  test('Action due time is entered as Asia/Shanghai wall time and the field says so', async ({ page }) => {
    await stubReadySession(page)
    const findingId = 'finding-action-due-zone'
    const caseId = 'case-action-due-zone'
    let createBody: Record<string, unknown> | null = null

    await stubFindingContext(page, findingId, caseId, () => 'rectifying', () => [], () => [])
    await page.route(
      (url) => url.pathname === `/api/v1/findings/${findingId}/actions`,
      (route) => {
        if (route.request().method() === 'GET') return fulfillJson(route, 200, [])
        createBody = route.request().postDataJSON() as Record<string, unknown>
        return fulfillJson(route, 422, { detail: 'stop after capturing the request' })
      },
    )

    await page.goto(`/findings/${findingId}`)
    await page.getByRole('button', { name: '新建整改项', exact: true }).click()
    const drawer = page.getByRole('dialog', { name: '新建整改项' })
    const dueAt = drawer.getByLabel('到期时间')
    await expect(dueAt).toHaveAccessibleDescription('以下时间均按上海时间（Asia/Shanghai）填写和显示。')
    await drawer.getByLabel('标题').fill('Zone Action')
    await dueAt.fill('2026/08/28 18:00')
    await dueAt.press('Enter')
    await drawer.getByLabel('标题').click()
    await drawer.getByRole('button', { name: '创建整改项' }).click()

    await expect.poll(() => createBody).not.toBeNull()
    expect(createBody).toMatchObject({ title: 'Zone Action', due_at: '2026-08-28T10:00:00.000Z' })
  })
})
