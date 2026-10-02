import { expect, test, type Page, type Route } from '@playwright/test'
import { notificationViewLabel, notificationViewRadio } from './notificationView.js'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'M3.5.4 Acceptance User',
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

function notification(
  id: string,
  title: string,
  readAt: string | null,
  subjectKind: 'review_case' | 'finding' | 'action_item' = 'finding',
  subjectId = 'finding-notification-target',
) {
  return {
    id,
    kind: 'manual_finding_nudge',
    origin_kind: 'activity',
    origin_activity_id: `activity-${id}`,
    automatic_origin_key: null,
    subject: { kind: subjectKind, id: subjectId },
    title,
    body: `Body ${title}`,
    created_at: '2026-08-28T12:00:00Z',
    read_at: readAt,
  }
}

function managementCase(id: string, title: string, deadlineBucket: string) {
  return {
    id,
    review_plan_id: null,
    title,
    scenario_key: 'process_review',
    scenario_version: 1,
    lifecycle: 'in_progress',
    planned_start_at: '2026-08-20T00:00:00Z',
    planned_end_at: '2026-08-29T00:00:00Z',
    deadline_bucket: deadlineBucket,
    findings: {
      total: 5,
      open: 1,
      rectifying: 2,
      verifying: 1,
      closed: 1,
      voided: 0,
    },
    actions: {
      total: 7,
      todo: 2,
      in_progress: 2,
      done: 2,
      cancelled: 1,
      overdue: 2,
      due_soon: 1,
    },
  }
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

function finding(id: string, caseId: string) {
  return {
    id,
    organization_id: user.organization_id,
    case_id: caseId,
    title: `Finding ${id}`,
    description: null,
    severity: 'high',
    lifecycle: 'rectifying',
    scenario_data: { issue_type: 'control_gap', project_category: 'assembly' },
    raised_by: user.id,
    raised_at: '2026-08-28T01:00:00Z',
  }
}

async function stubFindingChildren(page: Page, findingId: string) {
  for (const suffix of ['participant-views', 'actions', 'submissions', 'activities']) {
    await page.route((url) => url.pathname === `/api/v1/findings/${findingId}/${suffix}`, (route) =>
      fulfillJson(route, 200, []),
    )
  }
}

function deferred() {
  let release!: () => void
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  return { promise, release }
}

test('Notification 未读视图来自 server unread_only query and mark-read refetches authoritative collection', async ({ page }) => {
  await stubReadySession(page)
  let unreadRows = [notification('unread-1', 'Server-only unread row', null)]
  const requestedModes: string[] = []

  await page.route((url) => url.pathname === '/api/v1/me/notifications', (route) => {
    const url = new URL(route.request().url())
    const unreadOnly = url.searchParams.get('unread_only') ?? 'false'
    requestedModes.push(unreadOnly)
    if (unreadOnly === 'true') {
      return fulfillJson(route, 200, {
        items: unreadRows,
        unread_count: unreadRows.length,
        limit: 20,
        offset: Number(url.searchParams.get('offset') ?? '0'),
      })
    }
    return fulfillJson(route, 200, {
      items: [notification('read-1', 'Current all-page read row', '2026-08-28T12:10:00Z')],
      unread_count: unreadRows.length,
      limit: 20,
      offset: 0,
    })
  })

  await page.route(
    (url) => url.pathname === '/api/v1/me/notifications/unread-1/read',
    (route) => {
      expect(route.request().postData()).toBeNull()
      unreadRows = []
      return fulfillJson(route, 200, {
        ...notification('unread-1', 'Server-only unread row', '2026-08-28T12:20:00Z'),
      })
    },
  )

  await page.goto('/me/notifications')
  await expect(page.getByText('Current all-page read row', { exact: true })).toBeVisible()
  await expect(page.getByText('Server-only unread row', { exact: true })).toHaveCount(0)

  await notificationViewLabel(page, /未读/).click()
  await expect(notificationViewRadio(page, /未读/)).toBeChecked()
  await expect(page.getByText('Server-only unread row', { exact: true })).toBeVisible()
  await expect(page.getByText('Current all-page read row', { exact: true })).toHaveCount(0)
  expect(requestedModes).toContain('true')

  await page.getByRole('button', { name: '标记已读' }).click()
  await expect(page.getByText('没有未读通知。')).toBeVisible()
  await expect(page.getByText('未读总数 0')).toBeVisible()
})

test('mark-read 409 and unknown outcome refetch the list without replaying the write', async ({ page }) => {
  await stubReadySession(page)
  let listReads = 0
  let markRequests = 0
  const outcomes = [409, 'abort'] as const
  await page.route((url) => url.pathname === '/api/v1/me/notifications', (route) => {
    listReads += 1
    return fulfillJson(route, 200, {
      items: [notification('unread-1', 'Still unread row', null)],
      unread_count: 1,
      limit: 20,
      offset: 0,
    })
  })
  await page.route((url) => url.pathname === '/api/v1/me/notifications/unread-1/read', (route) => {
    const outcome = outcomes[markRequests]
    markRequests += 1
    if (outcome === 409) return fulfillJson(route, 409, { detail: 'Conflict' })
    return route.abort('failed')
  })

  await page.goto('/me/notifications')
  await expect(page.getByText('Still unread row', { exact: true })).toBeVisible()
  const initialReads = listReads

  await page.getByRole('button', { name: '标记已读' }).click()
  await expect(page.getByText('数据已变化，正在获取最新状态。')).toBeVisible()
  await expect.poll(() => listReads).toBe(initialReads + 1)
  await expect(page.getByText('Still unread row', { exact: true })).toBeVisible()
  expect(markRequests).toBe(1)

  await page.getByRole('button', { name: '标记已读' }).click()
  await expect(page.getByText(/未确认是否已标记为已读/)).toBeVisible()
  await expect.poll(() => listReads).toBe(initialReads + 2)
  expect(markRequests).toBe(2)
})

test('notification empty state tells an empty inbox from an empty unread filter', async ({ page }) => {
  await stubReadySession(page)
  await page.route((url) => url.pathname === '/api/v1/me/notifications', (route) =>
    fulfillJson(route, 200, { items: [], unread_count: 0, limit: 20, offset: 0 }),
  )
  await page.goto('/me/notifications')
  await expect(page.getByText('暂无通知。')).toBeVisible()
  await notificationViewLabel(page, /未读/).click()
  await expect(page.getByText('没有未读通知。')).toBeVisible()
  await page.getByRole('button', { name: '查看全部通知' }).click()
  await expect(page.getByText('暂无通知。')).toBeVisible()
})

test('historical Notification does not grant current Finding access', async ({ page }) => {
  await stubReadySession(page)
  const findingId = 'finding-currently-hidden'
  await page.route((url) => url.pathname === '/api/v1/me/notifications', (route) =>
    fulfillJson(route, 200, {
      items: [notification('historical-1', 'Historical receipt remains visible', null, 'finding', findingId)],
      unread_count: 1,
      limit: 20,
      offset: 0,
    }),
  )
  await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
    fulfillJson(route, 403, { detail: 'Current Finding access revoked' }),
  )

  await page.goto('/me/notifications')
  await expect(page.getByText('Historical receipt remains visible', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: '打开当前目标' }).click()
  await expect(page.getByRole('heading', { name: '发现项不可用' })).toBeVisible()
  await expect(page.getByText('Historical receipt remains visible', { exact: true })).toHaveCount(0)
})

test('late Management response cannot overwrite a newer server filter result', async ({ page }) => {
  await stubReadySession(page)
  const slowAll = deferred()

  await page.route((url) => url.pathname === '/api/v1/management/review-cases', async (route) => {
    const url = new URL(route.request().url())
    const deadline = url.searchParams.get('deadline_status')
    if (deadline === 'all') {
      await slowAll.promise
      return fulfillJson(route, 200, {
        as_of: '2026-08-28T12:00:00Z',
        items: [managementCase('case-old', 'Late all-filter result', 'later')],
        total: 1,
        limit: 20,
        offset: 0,
      })
    }
    return fulfillJson(route, 200, {
      as_of: '2026-08-28T12:01:00Z',
      items: [managementCase('case-overdue', 'Current overdue result', 'overdue')],
      total: 1,
      limit: 20,
      offset: 0,
    })
  })

  await page.goto('/management')
  await page.getByLabel('截止情况').selectOption('overdue')
  await expect(page.getByText('Current overdue result')).toBeVisible()
  slowAll.release()
  await page.waitForTimeout(50)
  await expect(page.getByText('Late all-filter result')).toHaveCount(0)
  await expect(page.getByText('共 1 项', { exact: true })).toBeVisible()
})

test('Management nudge shortcut calls original bodyless commands and displays only server fan-out result', async ({ page }) => {
  await stubReadySession(page)
  const caseId = 'case-management-nudge'
  const findingId = 'finding-management-nudge'
  const actionId = 'action-management-nudge'

  await page.route(
    (url) => url.pathname === `/api/v1/management/review-cases/${caseId}/progress`,
    (route) => fulfillJson(route, 200, {
      as_of: '2026-08-28T12:00:00Z',
      case: managementCase(caseId, 'Managed nudge case', 'overdue'),
      findings: [{
        id: findingId,
        title: 'Managed Finding',
        severity: 'high',
        lifecycle: 'rectifying',
        raised_at: '2026-08-28T01:00:00Z',
        actions: {
          total: 1,
          todo: 0,
          in_progress: 1,
          done: 0,
          cancelled: 0,
          overdue: 1,
          due_soon: 0,
        },
      }],
      overdue_actions: [{
        id: actionId,
        title: 'Managed Action',
        lifecycle: 'in_progress',
        due_at: '2026-08-27T00:00:00Z',
      }],
      due_soon_actions: [],
    }),
  )
  await page.route((url) => url.pathname === `/api/v1/findings/${findingId}/nudge`, (route) => {
    expect(route.request().postData()).toBeNull()
    return fulfillJson(route, 200, { activity_id: 'activity-finding-nudge', recipient_count: 2 })
  })
  await page.route((url) => url.pathname === `/api/v1/action-items/${actionId}/nudge`, (route) => {
    expect(route.request().postData()).toBeNull()
    return fulfillJson(route, 200, { activity_id: 'activity-action-nudge', recipient_count: 3 })
  })

  await page.goto(`/management/review-cases/${caseId}`)
  await expect(page.getByRole('heading', { name: 'Managed nudge case' })).toBeVisible()
  await page.getByRole('button', { name: '催办发现项' }).click()
  await expect(page.getByText(/已通知 2 人，操作记录 activity-finding-nudge/)).toBeVisible()
  await page.getByRole('button', { name: '催办整改项' }).click()
  await expect(page.getByText(/已通知 3 人，操作记录 activity-action-nudge/)).toBeVisible()
})

test('Finding nudge 422 stays authoritative and a late nudge result cannot leak across routes', async ({ page }) => {
  await stubReadySession(page)
  const caseA = 'case-nudge-a'
  const caseB = 'case-nudge-b'
  const findingA = 'finding-nudge-a'
  const findingB = 'finding-nudge-b'
  const slowNudge = deferred()

  for (const [findingId, caseId] of [[findingA, caseA], [findingB, caseB]] as const) {
    await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
      fulfillJson(route, 200, finding(findingId, caseId)),
    )
    await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}`, (route) =>
      fulfillJson(route, 200, reviewCase(caseId)),
    )
    await stubFindingChildren(page, findingId)
  }

  let mode: 'slow-success' | 'validation' = 'slow-success'
  await page.route((url) => url.pathname === `/api/v1/findings/${findingA}/nudge`, async (route) => {
    expect(route.request().postData()).toBeNull()
    if (mode === 'validation') {
      return fulfillJson(route, 422, { detail: 'No eligible nudge recipients' })
    }
    await slowNudge.promise
    return fulfillJson(route, 200, { activity_id: 'late-activity', recipient_count: 4 })
  })

  await page.goto(`/findings/${findingA}`)
  await page.getByRole('button', { name: '催办', exact: true }).click()
  await page.goto(`/findings/${findingB}`)
  await expect(page.getByRole('heading', { name: `Finding ${findingB}` })).toBeVisible()
  slowNudge.release()
  await page.waitForTimeout(50)
  await expect(page.getByText(/late-activity/)).toHaveCount(0)

  mode = 'validation'
  await page.goto(`/findings/${findingA}`)
  await page.getByRole('button', { name: '催办', exact: true }).click()
  await expect(page.getByText('No eligible nudge recipients')).toBeVisible()
  await expect(page.getByText(/服务器已确认催办/)).toHaveCount(0)
})
