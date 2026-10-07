import { expect, test, type Locator, type Page, type Route } from '@playwright/test'
import { notificationViewLabel, notificationViewRadio } from './notificationView.js'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'M3.5.5 Responsive User With A Deliberately Long Display Name',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
}

const caseId = 'case-responsive-00000000-0000-4000-8000-000000000001'
const findingId = 'finding-responsive-00000000-0000-4000-8000-000000000002'
const actionId = 'action-responsive-00000000-0000-4000-8000-000000000003'
const longTitle = 'Responsive acceptance title '.repeat(7).trim()

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function stubSession(page: Page) {
  await page.route((url) => url.pathname === '/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...user, must_change_password: false }),
  )
}

function reviewCase() {
  return {
    id: caseId,
    organization_id: user.organization_id,
    plan_id: null,
    scenario_key: 'process_review',
    scenario_version: 1,
    title: longTitle,
    lifecycle: 'in_progress',
    planned_start_at: '2026-08-20T00:00:00Z',
    planned_end_at: '2026-09-15T00:00:00Z',
    started_at: '2026-08-21T00:00:00Z',
    fieldwork_completed_at: null,
    closed_at: null,
    scenario_data: { area_code: 'RESPONSIVE-LINE-WITH-LONG-CONTENT', review_type: 'routine' },
    created_by: user.id,
    created_at: '2026-08-18T00:00:00Z',
  }
}

function finding() {
  return {
    id: findingId,
    organization_id: user.organization_id,
    case_id: caseId,
    title: longTitle,
    description: `${longTitle} ${longTitle}`,
    severity: 'high',
    lifecycle: 'rectifying',
    scenario_data: { issue_type: 'control_gap', project_category: 'assembly' },
    raised_by: user.id,
    raised_at: '2026-08-28T01:00:00Z',
  }
}

function action() {
  return {
    id: actionId,
    organization_id: user.organization_id,
    finding_id: findingId,
    title: longTitle,
    lifecycle: 'in_progress',
    due_at: '2026-08-30T00:00:00Z',
    completed_at: null,
  }
}

function managementCase() {
  return {
    id: caseId,
    review_plan_id: null,
    title: longTitle,
    scenario_key: 'process_review',
    scenario_version: 1,
    lifecycle: 'in_progress',
    planned_start_at: '2026-08-20T00:00:00Z',
    planned_end_at: '2026-08-29T00:00:00Z',
    deadline_bucket: 'overdue',
    findings: { total: 3, open: 0, rectifying: 1, verifying: 1, closed: 1, voided: 0 },
    actions: { total: 5, todo: 1, in_progress: 1, done: 2, cancelled: 1, overdue: 1, due_soon: 1 },
  }
}

async function stubWorkbench(page: Page) {
  await page.route((url) => url.pathname === '/api/v1/me/workbench', (route) =>
    fulfillJson(route, 200, {
      as_of: '2026-08-28T10:00:00Z',
      case_responsibilities: [{
        id: caseId,
        title: longTitle,
        lifecycle: 'in_progress',
        role_keys: ['lead'],
        planned_end_at: '2026-09-15T00:00:00Z',
      }],
      finding_responsibilities: [{
        id: findingId,
        case_id: caseId,
        title: longTitle,
        severity: 'high',
        lifecycle: 'rectifying',
        relationships: [],
        raised_at: '2026-08-28T01:00:00Z',
      }],
      action_responsibilities: [{
        id: actionId,
        finding_id: findingId,
        case_id: caseId,
        title: longTitle,
        lifecycle: 'in_progress',
        due_at: '2026-08-30T00:00:00Z',
        relationships: [],
      }],
      verification_queue: [],
      overdue: { cases: [], actions: [] },
      due_soon: { cases: [], actions: [] },
    }),
  )
}

async function stubCase(page: Page) {
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}`, (route) =>
    fulfillJson(route, 200, reviewCase()),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}/members`, (route) =>
    fulfillJson(route, 200, []),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}/findings`, (route) =>
    fulfillJson(route, 200, [finding()]),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${caseId}/activities`, (route) =>
    fulfillJson(route, 200, []),
  )
}

async function stubFinding(page: Page) {
  await page.route((url) => url.pathname === `/api/v1/findings/${findingId}`, (route) =>
    fulfillJson(route, 200, finding()),
  )
  for (const suffix of ['participant-views', 'submissions', 'activities']) {
    await page.route((url) => url.pathname === `/api/v1/findings/${findingId}/${suffix}`, (route) =>
      fulfillJson(route, 200, []),
    )
  }
  await page.route((url) => url.pathname === `/api/v1/findings/${findingId}/actions`, (route) =>
    fulfillJson(route, 200, [action()]),
  )
}

async function stubAction(page: Page) {
  await page.route((url) => url.pathname === `/api/v1/action-items/${actionId}`, (route) =>
    fulfillJson(route, 200, action()),
  )
  for (const suffix of ['assignee-views', 'evidences', 'activities']) {
    await page.route((url) => url.pathname === `/api/v1/action-items/${actionId}/${suffix}`, (route) =>
      fulfillJson(route, 200, []),
    )
  }
}

async function stubNotifications(page: Page) {
  await page.route((url) => url.pathname === '/api/v1/me/notifications', (route) =>
    fulfillJson(route, 200, {
      items: [{
        id: 'notification-responsive',
        kind: 'manual_finding_nudge',
        origin_kind: 'activity',
        origin_activity_id: 'activity-responsive',
        automatic_origin_key: null,
        subject: { kind: 'finding', id: findingId },
        title: longTitle,
        body: `${longTitle} ${longTitle}`,
        created_at: '2026-08-28T12:00:00Z',
        read_at: null,
      }],
      unread_count: 1,
      limit: 20,
      offset: 0,
    }),
  )
}

async function stubManagement(page: Page) {
  await page.route((url) => url.pathname === '/api/v1/management/review-cases', (route) =>
    fulfillJson(route, 200, {
      as_of: '2026-08-28T12:00:00Z',
      items: [managementCase()],
      total: 1,
      limit: 20,
      offset: 0,
    }),
  )
  await page.route((url) => url.pathname === `/api/v1/management/review-cases/${caseId}/progress`, (route) =>
    fulfillJson(route, 200, {
      as_of: '2026-08-28T12:00:00Z',
      case: managementCase(),
      findings: [{
        id: findingId,
        title: longTitle,
        severity: 'high',
        lifecycle: 'rectifying',
        raised_at: '2026-08-28T01:00:00Z',
        actions: { total: 1, todo: 0, in_progress: 1, done: 0, cancelled: 0, overdue: 1, due_soon: 0 },
      }],
      overdue_actions: [{ id: actionId, title: longTitle, lifecycle: 'in_progress', due_at: '2026-08-27T00:00:00Z' }],
      due_soon_actions: [],
    }),
  )
}

async function stubProduct(page: Page) {
  await stubSession(page)
  await stubWorkbench(page)
  await stubCase(page)
  await stubFinding(page)
  await stubAction(page)
  await stubNotifications(page)
  await stubManagement(page)
}

async function expectNoDocumentOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() => {
    const browser = globalThis as unknown as {
      document: { documentElement: { scrollWidth: number; clientWidth: number } }
    }
    return browser.document.documentElement.scrollWidth - browser.document.documentElement.clientWidth
  })).toBeLessThanOrEqual(1)
}

async function expectInsideViewport(page: Page, locator: Locator) {
  const box = await locator.boundingBox()
  const viewport = page.viewportSize()
  expect(box).not.toBeNull()
  expect(box!.x).toBeGreaterThanOrEqual(0)
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width + 1)
}

async function visibleOutline(locator: Locator) {
  return locator.evaluate((element) => {
    const browser = globalThis as unknown as {
      getComputedStyle: (target: unknown) => { outlineStyle: string; outlineWidth: string }
    }
    const style = browser.getComputedStyle(element)
    return { style: style.outlineStyle, width: style.outlineWidth }
  })
}

test('M3.5.5 narrow product route matrix keeps essential controls inside the document viewport', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await stubProduct(page)

  const routes = [
    ['/me/workbench', '我的工作'],
    [`/review-cases/${caseId}`, longTitle],
    [`/findings/${findingId}`, longTitle],
    [`/action-items/${actionId}`, longTitle],
    ['/me/notifications', '通知'],
    ['/management', '管理视图'],
    [`/management/review-cases/${caseId}`, longTitle],
  ] as const

  for (const [path, heading] of routes) {
    await page.goto(path)
    await expect(page.getByRole('heading', { name: heading }).first(), path).toBeVisible()
    await expectNoDocumentOverflow(page)
  }
  await expect(page.getByText(user.display_name)).toBeVisible()

  await page.goto(`/findings/${findingId}`)
  await expect(page.getByRole('button', { name: '催办', exact: true })).toBeVisible()
  await page.goto(`/action-items/${actionId}`)
  await expect(page.getByRole('button', { name: '完成' })).toBeVisible()
  await page.goto('/me/notifications')
  await expect(notificationViewLabel(page, /未读/)).toBeVisible()
  await page.goto('/management')
  await expect(page.getByRole('radiogroup', { name: '截止情况' })).toBeVisible()
})

test('M3.5.5 320px smoke keeps Workbench and dense Management progress free of document overflow', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 })
  await stubProduct(page)

  await page.goto('/me/workbench')
  await expectNoDocumentOverflow(page)
  await expect(page.getByRole('link', { name: longTitle }).first()).toBeVisible()

  await page.goto(`/management/review-cases/${caseId}`)
  await expectNoDocumentOverflow(page)
  await expect(page.getByRole('button', { name: '催办发现项' })).toBeVisible()
})

test('M3.5.5 keyboard focus is visible and primary navigation remains keyboard-operable', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await stubProduct(page)
  await page.goto('/me/workbench')

  const nav = page.getByRole('navigation', { name: '主要导航' })
  const notificationLink = nav.getByRole('link', { name: '通知' })
  await notificationLink.focus()
  await expect(notificationLink).toBeFocused()
  const linkOutline = await visibleOutline(notificationLink)
  expect(linkOutline.style).not.toBe('none')
  expect(linkOutline.width).not.toBe('0px')
  await notificationLink.press('Enter')
  await expect(page).toHaveURL(/\/me\/notifications$/)
  await expect(page.getByRole('heading', { name: '通知' })).toBeVisible()

  // 视图切换是 Radio.Group：聚焦后方向键切换，焦点环画在所属 label 上。
  await page.getByRole('radio', { name: '全部' }).focus()
  await expect(notificationViewRadio(page, '全部')).toBeChecked()
  await page.keyboard.press('ArrowRight')
  await expect(notificationViewRadio(page, /未读/)).toBeChecked()
  await expect(notificationViewRadio(page, /未读/)).toBeFocused()
  expect((await visibleOutline(notificationViewLabel(page, /未读/))).style).not.toBe('none')
})

for (const width of [375, 320]) {
  test(`Workbench and notification center keep task entries and unread actions usable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 740 })
    await stubProduct(page)

    await page.goto('/me/workbench')
    await expect(page.getByRole('heading', { name: '我的工作' })).toBeVisible()
    await expectNoDocumentOverflow(page)
    const workLink = page.getByRole('link', { name: longTitle }).first()
    await expect(workLink).toBeVisible()
    await expectInsideViewport(page, workLink)

    await page.goto('/me/notifications')
    await expect(page.getByRole('heading', { name: '通知' })).toBeVisible()
    await expectNoDocumentOverflow(page)
    for (const control of [
      notificationViewLabel(page, /未读/),
      page.getByRole('link', { name: '打开当前目标' }),
      page.getByRole('button', { name: '标记已读' }),
      page.getByRole('button', { name: '下一页' }),
    ]) {
      await expect(control).toBeVisible()
      await expectInsideViewport(page, control)
    }
  })
}

test('M3.5.5 management nudge success survives authoritative same-case refetch', async ({ page }) => {
  await stubProduct(page)
  let progressReads = 0
  await page.unroute((url) => url.pathname === `/api/v1/management/review-cases/${caseId}/progress`)
  await page.route((url) => url.pathname === `/api/v1/management/review-cases/${caseId}/progress`, (route) => {
    progressReads += 1
    return fulfillJson(route, 200, {
      as_of: `2026-08-28T12:0${Math.min(progressReads, 9)}:00Z`,
      case: managementCase(),
      findings: [{
        id: findingId,
        title: longTitle,
        severity: 'high',
        lifecycle: 'rectifying',
        raised_at: '2026-08-28T01:00:00Z',
        actions: { total: 1, todo: 0, in_progress: 1, done: 0, cancelled: 0, overdue: 1, due_soon: 0 },
      }],
      overdue_actions: [],
      due_soon_actions: [],
    })
  })
  await page.route((url) => url.pathname === `/api/v1/findings/${findingId}/nudge`, (route) => {
    expect(route.request().postData()).toBeNull()
    return fulfillJson(route, 200, { activity_id: 'activity-stable-feedback', recipient_count: 2 })
  })

  await page.goto(`/management/review-cases/${caseId}`)
  await page.getByRole('button', { name: '催办发现项' }).click()
  await expect(page.getByText('服务器已确认催办：已通知 2 人。')).toBeVisible()
  await expect.poll(() => progressReads).toBeGreaterThan(1)
  await expect(page.getByText('服务器已确认催办：已通知 2 人。')).toBeVisible()
})
