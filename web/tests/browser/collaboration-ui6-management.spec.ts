import { expect, test, type Page, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'UI-6 Acceptance User',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
}

const LIST_PATH = '/api/v1/management/review-cases'
const EXPORT_PATH = '/api/v1/management/review-cases/export'

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function stubSession(page: Page) {
  await page.route((url) => url.pathname === '/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...user, must_change_password: false }),
  )
}

function managementCase(id: string, title: string) {
  return {
    id,
    review_plan_id: null,
    title,
    scenario_key: 'process_review',
    scenario_version: 1,
    lifecycle: 'in_progress',
    planned_start_at: '2026-08-20T00:00:00Z',
    planned_end_at: '2026-08-29T00:00:00Z',
    deadline_bucket: 'overdue',
    findings: { total: 6, open: 1, rectifying: 2, verifying: 1, closed: 1, voided: 1 },
    actions: { total: 7, todo: 1, in_progress: 2, done: 2, cancelled: 1, overdue: 1, due_soon: 1 },
  }
}

function listBody(items: unknown[], total = items.length, offset = 0) {
  return { as_of: '2026-08-28T10:00:00Z', items, total, limit: 20, offset }
}

async function expectNoDocumentOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() => {
    const browser = globalThis as unknown as {
      document: { documentElement: { scrollWidth: number; clientWidth: number } }
    }
    return browser.document.documentElement.scrollWidth - browser.document.documentElement.clientWidth
  })).toBeLessThanOrEqual(1)
}

test('管理视图展示后端指标与 as_of（Asia/Shanghai），不推导任何统计', async ({ page }) => {
  await stubSession(page)
  await page.route((url) => url.pathname === LIST_PATH, (route) =>
    fulfillJson(route, 200, listBody([managementCase('case-1', 'Metrics case')], 41)),
  )
  await page.goto('/management')

  await expect(page.getByText('数据时间 2026/08/28 18:00')).toBeVisible()
  const row = page.getByRole('row').filter({ hasText: 'Metrics case' })
  await expect(row).toContainText('共 6 / 待处理 1 / 整改中 2 / 待验证 1 / 已关闭 1 / 已作废 1')
  await expect(row).toContainText('共 7 / 待开始 1 / 执行中 2 / 已完成 2 / 已取消 1 / 已逾期 1 / 即将到期 1')
  await expect(row).toContainText('已逾期')
  await expect(page.getByText('共 41 项', { exact: true })).toBeVisible()
  await expect(row.getByRole('link', { name: '查看管理进度' })).toHaveAttribute('href', '/management/review-cases/case-1')
})

test('筛选、分页与导出使用同一组参数', async ({ page }) => {
  await stubSession(page)
  const listed: URL[] = []
  const exported: URL[] = []
  await page.route((url) => url.pathname === LIST_PATH, (route) => {
    listed.push(new URL(route.request().url()))
    return fulfillJson(route, 200, listBody([managementCase('case-1', 'Filtered case')], 45))
  })
  await page.route((url) => url.pathname === EXPORT_PATH, (route) => {
    exported.push(new URL(route.request().url()))
    return route.fulfill({
      status: 200,
      headers: {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': 'attachment; filename="review-cases.csv"',
      },
      body: 'a,b\r\n',
    })
  })
  await page.goto('/management')
  await expect(page.getByText('Filtered case')).toBeVisible()

  await page.getByRole('radio', { name: '即将到期' }).click()
  await page.getByLabel('审查活动状态').click()
  await page.getByTitle('待关闭', { exact: true }).click()
  await page.getByLabel('审查计划 ID').fill(' plan-9 ')
  await page.getByRole('button', { name: '按审查计划筛选' }).click()
  await expect.poll(() => listed.at(-1)?.searchParams.get('review_plan_id')).toBe('plan-9')
  await page.getByRole('button', { name: '下一页' }).click()
  await expect.poll(() => listed.at(-1)?.searchParams.get('offset')).toBe('20')

  const last = listed.at(-1)
  expect(last?.searchParams.get('deadline_status')).toBe('due_soon')
  expect(last?.searchParams.get('lifecycle')).toBe('awaiting_closure')
  expect(last?.searchParams.get('limit')).toBe('20')

  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出 CSV' }).click()
  await download
  expect(exported).toHaveLength(1)
  expect(exported[0]?.searchParams.get('format')).toBe('csv')
  expect(exported[0]?.searchParams.get('deadline_status')).toBe('due_soon')
  expect(exported[0]?.searchParams.get('lifecycle')).toBe('awaiting_closure')
  expect(exported[0]?.searchParams.get('review_plan_id')).toBe('plan-9')
  expect(exported[0]?.searchParams.has('offset')).toBe(false)

  await page.getByRole('button', { name: '清除筛选' }).click()
  await expect.poll(() => listed.at(-1)?.searchParams.get('deadline_status')).toBe('all')
  expect(listed.at(-1)?.searchParams.has('lifecycle')).toBe(false)
  expect(listed.at(-1)?.searchParams.has('review_plan_id')).toBe(false)
  expect(listed.at(-1)?.searchParams.get('offset')).toBe('0')
})

test('管理视图 403 时移除受保护内容并给出中性提示', async ({ page }) => {
  await stubSession(page)
  let denied = false
  await page.route((url) => url.pathname === LIST_PATH, (route) =>
    denied
      ? fulfillJson(route, 403, { detail: 'Management access required' })
      : fulfillJson(route, 200, listBody([managementCase('case-1', 'Revoked case')])),
  )
  await page.goto('/management')
  await expect(page.getByText('Revoked case')).toBeVisible()

  denied = true
  await page.getByRole('radio', { name: '已逾期' }).click()
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByText('Revoked case')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '导出 CSV' })).toHaveCount(0)
  await expect(page.getByText('Management access required')).toHaveCount(0)
})

test('管理视图导出 403 同样移除内容', async ({ page }) => {
  await stubSession(page)
  await page.route((url) => url.pathname === LIST_PATH, (route) =>
    fulfillJson(route, 200, listBody([managementCase('case-1', 'Export denied case')])),
  )
  await page.route((url) => url.pathname === EXPORT_PATH, (route) =>
    fulfillJson(route, 403, { detail: 'Management access required' }),
  )
  await page.goto('/management')
  await page.getByRole('button', { name: '导出 XLSX' }).click()
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByText('Export denied case')).toHaveCount(0)
})

test('管理视图空数据与加载失败', async ({ page }) => {
  await stubSession(page)
  let fail = true
  await page.route((url) => url.pathname === LIST_PATH, (route) =>
    fail
      ? fulfillJson(route, 500, { detail: 'boom' })
      : fulfillJson(route, 200, listBody([])),
  )
  await page.goto('/management')
  await expect(page.getByRole('alert').filter({ hasText: 'boom' })).toBeVisible()
  await expect(page.getByText('数据时间')).toHaveCount(0)

  fail = false
  await page.getByRole('button', { name: '重新加载' }).click()
  await expect(page.getByText('当前筛选下没有可管理的审查活动。')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByText('数据时间 2026/08/28 18:00')).toBeVisible()
})

function progressBody() {
  return {
    as_of: '2026-08-28T10:00:00Z',
    case: managementCase('case-1', 'Progress case'),
    findings: [{
      id: 'finding-1',
      title: 'Progress finding',
      severity: 'high',
      lifecycle: 'rectifying',
      raised_at: '2026-08-21T00:00:00Z',
      actions: { total: 2, todo: 0, in_progress: 1, done: 1, cancelled: 0, overdue: 1, due_soon: 0 },
    }],
    overdue_actions: [{ id: 'action-1', title: 'Overdue action', lifecycle: 'in_progress', due_at: '2026-08-25T00:00:00Z' }],
    due_soon_actions: [],
  }
}

test('管理进度展示后端计数并按 Asia/Shanghai 显示时间', async ({ page }) => {
  await stubSession(page)
  await page.route((url) => url.pathname === `${LIST_PATH}/case-1/progress`, (route) =>
    fulfillJson(route, 200, progressBody()),
  )
  await page.goto('/management/review-cases/case-1')

  await expect(page.getByRole('heading', { name: 'Progress case', level: 1 })).toBeVisible()
  await expect(page.getByText('数据时间 2026/08/28 18:00')).toBeVisible()
  await expect(page.getByText('发现项总数').locator('xpath=..').getByText('6', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Progress finding' })).toHaveAttribute('href', '/findings/finding-1')
  await expect(page.getByRole('link', { name: 'Overdue action' })).toHaveAttribute('href', '/action-items/action-1')
  await expect(page.getByText('当前没有即将到期整改项。')).toBeVisible()
})

test('管理进度 403 移除受保护内容；催办 403 后重读并移除', async ({ page }) => {
  await stubSession(page)
  let denied = false
  await page.route((url) => url.pathname === `${LIST_PATH}/case-1/progress`, (route) =>
    denied
      ? fulfillJson(route, 403, { detail: 'Management access required' })
      : fulfillJson(route, 200, progressBody()),
  )
  await page.route((url) => url.pathname === '/api/v1/findings/finding-1/nudge', (route) => {
    denied = true
    return fulfillJson(route, 403, { detail: 'Management access required' })
  })
  await page.goto('/management/review-cases/case-1')
  await expect(page.getByRole('link', { name: 'Progress finding' })).toBeVisible()

  await page.getByRole('button', { name: '催办发现项' }).click()
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByText('Progress finding')).toHaveCount(0)
  await expect(page.getByText('Progress case')).toHaveCount(0)
})

test('管理进度加载失败可重新加载', async ({ page }) => {
  await stubSession(page)
  let fail = true
  await page.route((url) => url.pathname === `${LIST_PATH}/case-1/progress`, (route) =>
    fail ? fulfillJson(route, 500, { detail: 'boom' }) : fulfillJson(route, 200, progressBody()),
  )
  await page.goto('/management/review-cases/case-1')
  await expect(page.getByRole('alert').filter({ hasText: 'boom' })).toBeVisible()
  fail = false
  await page.getByRole('button', { name: '重新加载' }).click()
  await expect(page.getByRole('heading', { name: 'Progress case', level: 1 })).toBeVisible()
})

for (const width of [375, 320]) {
  test(`管理视图与管理进度在 ${width}px 无文档级横向溢出`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await stubSession(page)
    await page.route((url) => url.pathname === LIST_PATH, (route) =>
      fulfillJson(route, 200, listBody([managementCase('case-1', 'Narrow case')], 45)),
    )
    await page.route((url) => url.pathname === `${LIST_PATH}/case-1/progress`, (route) =>
      fulfillJson(route, 200, progressBody()),
    )

    await page.goto('/management')
    await expect(page.getByText('Narrow case')).toBeVisible()
    await expectNoDocumentOverflow(page)
    await expect(page.getByRole('button', { name: '导出 CSV' })).toBeVisible()

    await page.goto('/management/review-cases/case-1')
    await expect(page.getByRole('link', { name: 'Progress finding' })).toBeVisible()
    await expectNoDocumentOverflow(page)
  })
}

test('1280px 下管理视图操作列链接在视口内且不显示内部场景标识', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await stubSession(page)
  await page.route((url) => url.pathname === LIST_PATH, (route) =>
    fulfillJson(route, 200, listBody([managementCase('case-1', 'Wide case')])),
  )
  await page.goto('/management')
  const row = page.getByRole('row').filter({ hasText: 'Wide case' })
  await expect(row).toBeVisible()
  await expect(row.getByRole('link', { name: '查看管理进度' })).toBeInViewport({ ratio: 1 })
  await expect(row.getByRole('link', { name: '打开审查活动' })).toBeInViewport({ ratio: 1 })
  await expect(row).toContainText('过程审查')
  await expect(page.getByText('process_review', { exact: false })).toHaveCount(0)
  await expectNoDocumentOverflow(page)
})
