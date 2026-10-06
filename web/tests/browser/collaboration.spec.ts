import { expect, test, type Page, type Route } from '@playwright/test'

import { openAssignDrawer, pickCandidate } from './assignmentDrawer.js'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'Collaboration User',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
}

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function stubReadySession(page: Page) {
  await page.route((url) => url.pathname === '/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...user, must_change_password: false }),
  )
}

function caseResponse(id = 'case-1', version = 1) {
  return {
    id,
    organization_id: user.organization_id,
    plan_id: null,
    scenario_key: 'process_review',
    scenario_version: version,
    title: 'Collaboration Case',
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

function findingResponse(id = 'finding-1', lifecycle = 'open') {
  return {
    id,
    organization_id: user.organization_id,
    case_id: 'case-1',
    title: 'Calibration evidence gap',
    description: 'Calibration record is missing.',
    severity: 'high',
    lifecycle,
    scenario_data: { issue_type: 'control_gap', project_category: 'assembly' },
    raised_by: user.id,
    raised_at: '2026-08-28T01:00:00Z',
  }
}

function actionResponse(id = 'action-1', lifecycle = 'todo') {
  return {
    id,
    organization_id: user.organization_id,
    finding_id: 'finding-1',
    title: 'Restore calibration record',
    lifecycle,
    due_at: '2026-08-30T00:00:00Z',
    completed_at: lifecycle === 'done' ? '2026-08-29T00:00:00Z' : null,
  }
}

async function stubFindingChildren(page: Page, findingId = 'finding-1') {
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

async function stubActionChildren(page: Page, actionId = 'action-1') {
  await page.route(
    (url) => url.pathname === `/api/v1/action-items/${actionId}/assignee-views`,
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/action-items/${actionId}/activities`,
    (route) => fulfillJson(route, 200, []),
  )
}

test('Finding primary refusal prevents all subordinate reads and protected stale content', async ({ page }) => {
  await stubReadySession(page)
  let subordinateRequests = 0
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (path.startsWith('/api/v1/findings/blocked/') || path === '/api/v1/review-cases/case-1') {
      subordinateRequests += 1
    }
  })
  await page.route(
    (url) => url.pathname === '/api/v1/findings/blocked',
    (route) => fulfillJson(route, 404, { detail: 'Finding not found' }),
  )

  await page.goto('/findings/blocked')
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByRole('heading', { level: 1, name: '发现项' })).toBeVisible()
  await expect(page.getByText('Calibration evidence gap')).toHaveCount(0)
  expect(subordinateRequests).toBe(0)
})

test('Action primary refusal prevents assignee evidence activity and parent reads', async ({ page }) => {
  await stubReadySession(page)
  let subordinateRequests = 0
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (path.startsWith('/api/v1/action-items/blocked/') || path.startsWith('/api/v1/findings/')) {
      subordinateRequests += 1
    }
  })
  await page.route(
    (url) => url.pathname === '/api/v1/action-items/blocked',
    (route) => fulfillJson(route, 403, { detail: 'Forbidden' }),
  )

  await page.goto('/action-items/blocked')
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByRole('heading', { level: 1, name: '整改项' })).toBeVisible()
  await expect(page.getByText('Restore calibration record')).toHaveCount(0)
  expect(subordinateRequests).toBe(0)
})

test('exact process_review@1 Finding renders Scenario data while unknown version fails closed', async ({ page }) => {
  await stubReadySession(page)
  let version = 1
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-1',
    (route) => fulfillJson(route, 200, findingResponse()),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/review-cases/case-1',
    (route) => fulfillJson(route, 200, caseResponse('case-1', version)),
  )
  await stubFindingChildren(page)

  await page.goto('/findings/finding-1')
  await expect(page.getByRole('heading', { name: 'Calibration evidence gap' })).toBeVisible()
  await expect(page.getByText('control_gap')).toBeVisible()
  await expect(page.getByText('assembly')).toBeVisible()
  await expect(page.getByRole('heading', { name: '业务操作' })).toBeVisible()

  version = 99
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Calibration evidence gap' })).toBeVisible()
  await expect(page.getByText('暂不支持当前版本的审查场景界面（过程审查 · process_review@99）。仍可查看发现项的通用信息。')).toBeVisible()
  await expect(page.getByRole('heading', { name: '业务操作' })).toHaveCount(0)
})

test('stale participant add 409 refetches terminal Finding and never persists a local relationship', async ({ page }) => {
  await stubReadySession(page)
  let lifecycle = 'open'
  let participantPostCount = 0
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-1',
    (route) => fulfillJson(route, 200, findingResponse('finding-1', lifecycle)),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/review-cases/case-1',
    (route) => fulfillJson(route, 200, caseResponse()),
  )
  await stubFindingChildren(page)
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-1/participant-candidates',
    (route) => fulfillJson(route, 200, [
      { actor_kind: 'department', actor_id: 'dept-1', display_name: 'Quality Department' },
    ]),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-1/participants',
    (route) => {
      participantPostCount += 1
      lifecycle = 'closed'
      return fulfillJson(route, 409, { detail: 'Concurrent Finding transition' })
    },
  )

  await page.goto('/findings/finding-1')
  const drawer = await openAssignDrawer(page, '添加参与人', '添加参与人')
  await pickCandidate(drawer, '参与人', 'Quality', 'Quality Department')
  await drawer.getByRole('button', { name: '添加参与人' }).click()

  await expect(drawer.getByRole('alert')).toContainText('数据已变化，正在获取最新状态')
  await expect(page.getByRole('article').locator('header').getByText('已关闭', { exact: true })).toBeVisible()
  await expect(page.getByText('暂无参与关系。')).toBeVisible()
  await expect(page.getByText('Quality Department')).toHaveCount(0)
  expect(participantPostCount).toBe(1)
})

test('Action stale transition 409 refetches server lifecycle and Evidence stays metadata-only', async ({ page }) => {
  await stubReadySession(page)
  let lifecycle = 'todo'
  await page.route(
    (url) => url.pathname === '/api/v1/action-items/action-1',
    (route) => fulfillJson(route, 200, actionResponse('action-1', lifecycle)),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-1',
    (route) => fulfillJson(route, 200, findingResponse('finding-1', 'rectifying')),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/review-cases/case-1',
    (route) => fulfillJson(route, 200, caseResponse()),
  )
  await stubActionChildren(page)
  await page.route(
    (url) => url.pathname === '/api/v1/action-items/action-1/evidences',
    (route) => fulfillJson(route, 200, [
      {
        id: 'evidence-1',
        organization_id: user.organization_id,
        action_item_id: 'action-1',
        storage_key: 'private/storage/key',
        original_name: 'calibration-report.pdf',
        content_type: 'application/pdf',
        size_bytes: 2048,
        sha256: 'a'.repeat(64),
        description: 'Calibration report',
        uploaded_by: user.id,
        created_at: '2026-08-28T03:00:00Z',
      },
    ]),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/action-items/action-1/transitions',
    (route) => {
      lifecycle = 'in_progress'
      return fulfillJson(route, 409, { detail: 'Concurrent ActionItem transition' })
    },
  )

  await page.goto('/action-items/action-1')
  await expect(page.getByText('calibration-report.pdf')).toBeVisible()
  await expect(page.getByText('private/storage/key')).toHaveCount(0)
  await expect(page.getByText('a'.repeat(64))).toHaveCount(0)
  await page.getByRole('button', { name: '开始整改项', exact: true }).click()

  await expect(page.getByRole('article').locator('header').getByText('执行中', { exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).not.toContainText('Concurrent ActionItem')
  await expect(page.getByRole('alert')).toContainText('数据已变化，正在获取最新状态')
})

test('Finding creation uses server response as truth and validation failure creates no local row', async ({ page }) => {
  await stubReadySession(page)
  let shouldSucceed = false
  await page.route(
    (url) => url.pathname === '/api/v1/review-cases/case-1',
    (route) => fulfillJson(route, 200, caseResponse()),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/review-cases/case-1/members',
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/review-cases/case-1/activities',
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/management/review-cases/case-1/progress',
    (route) => fulfillJson(route, 404, { detail: 'Not available' }),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/review-cases/case-1/findings',
    (route) => {
      if (route.request().method() === 'POST') {
        return shouldSucceed
          ? fulfillJson(route, 201, findingResponse('finding-new', 'open'))
          : fulfillJson(route, 422, { detail: 'Scenario validation failed' })
      }
      return fulfillJson(route, 200, [])
    },
  )

  await page.goto('/review-cases/case-1')
  await page.getByLabel('标题').fill('New Finding')
  await page.getByLabel('问题类型').fill('control_gap')
  await page.getByLabel('项目类别').fill('assembly')
  await page.getByRole('button', { name: '新建发现项' }).click()
  await expect(page.getByRole('alert')).toContainText('Scenario validation failed')
  await expect(page.getByText('暂无可见的发现项。')).toBeVisible()
  await expect(page).toHaveURL(/\/review-cases\/case-1$/)

  shouldSucceed = true
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-new',
    (route) => fulfillJson(route, 200, findingResponse('finding-new', 'open')),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-new/participant-views',
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-new/actions',
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-new/submissions',
    (route) => fulfillJson(route, 200, []),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/findings/finding-new/activities',
    (route) => fulfillJson(route, 200, []),
  )

  await page.getByRole('button', { name: '新建发现项' }).click()
  await expect(page).toHaveURL(/\/findings\/finding-new$/)
  await expect(page.getByRole('heading', { name: 'Calibration evidence gap' })).toBeVisible()
})
