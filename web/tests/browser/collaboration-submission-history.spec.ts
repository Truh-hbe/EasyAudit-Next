import { expect, test, type Page, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'History User',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
}

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

function submission(id: string, purpose: string, at: string, payload: Record<string, unknown>) {
  return {
    id,
    organization_id: user.organization_id,
    case_id: 'case-history',
    finding_id: 'finding-history',
    purpose,
    submitted_by: user.id,
    submitted_at: at,
    payload,
  }
}

const PLAN = submission('s1', 'rectification', '2026-09-01T01:00:00Z', { stage: 'plan', root_cause: '校准计划缺失原因' })
const COMPLETION = submission('s2', 'rectification', '2026-09-02T01:00:00Z', { stage: 'completion', comment: '首轮整改完成说明' })
const REJECTION = submission('s3', 'verification', '2026-09-03T01:00:00Z', {
  result: 'rejected',
  comment: '需补充下一班次的校准确认',
})

async function stubFinding(page: Page, scenarioKey: string, lifecycle: string, submissions: unknown[]) {
  await page.route((url) => url.pathname === '/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...user, must_change_password: false }),
  )
  await page.route((url) => url.pathname === '/api/v1/findings/finding-history', (route) =>
    fulfillJson(route, 200, {
      id: 'finding-history',
      organization_id: user.organization_id,
      case_id: 'case-history',
      title: 'History Finding',
      description: 'Description',
      severity: 'high',
      lifecycle,
      scenario_data:
        scenarioKey === 'process_review'
          ? { issue_type: 'control_gap', project_category: 'assembly' }
          : { criterion_reference: '8.5.1', finding_type: 'nonconformity' },
      raised_by: user.id,
      raised_at: '2026-08-28T01:00:00Z',
    }),
  )
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-history', (route) =>
    fulfillJson(route, 200, {
      id: 'case-history',
      organization_id: user.organization_id,
      plan_id: null,
      scenario_key: scenarioKey,
      scenario_version: 1,
      title: 'History Case',
      lifecycle: 'in_progress',
      planned_start_at: null,
      planned_end_at: null,
      started_at: '2026-08-28T00:00:00Z',
      fieldwork_completed_at: null,
      closed_at: null,
      scenario_data:
        scenarioKey === 'process_review'
          ? { area_code: 'A-01', review_type: 'routine' }
          : { standard_reference: 'ISO 9001', scope_summary: 'Line' },
      created_by: user.id,
      created_at: '2026-08-28T00:00:00Z',
    }),
  )
  for (const child of ['participant-views', 'actions', 'activities']) {
    await page.route((url) => url.pathname === `/api/v1/findings/finding-history/${child}`, (route) =>
      fulfillJson(route, 200, []),
    )
  }
  await page.route((url) => url.pathname === '/api/v1/findings/finding-history/submissions', (route) =>
    fulfillJson(route, 200, submissions),
  )
}

const history = (page: Page) => page.getByRole('list', { name: '提交记录' })
const notice = (page: Page) => page.getByRole('status').filter({ hasText: '最近一次验证被驳回' })

for (const scenarioKey of ['process_review', 'compliance_review']) {
  test(`${scenarioKey}@1: owner sees the rejection reason on top and the full history in order`, async ({ page }) => {
    await stubFinding(page, scenarioKey, 'rectifying', [PLAN, COMPLETION, REJECTION])
    await page.goto('/findings/finding-history')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('History Finding')

    await expect(notice(page)).toContainText('需补充下一班次的校准确认')
    const items = history(page).getByRole('listitem')
    await expect(items).toHaveCount(3)
    await expect(items.nth(0)).toContainText('整改计划')
    await expect(items.nth(0)).toContainText('根本原因')
    await expect(items.nth(0)).toContainText('校准计划缺失原因')
    await expect(items.nth(1)).toContainText('整改完成说明')
    await expect(items.nth(1)).toContainText('首轮整改完成说明')
    await expect(items.nth(2)).toContainText('验证驳回')
    await expect(items.nth(2)).toContainText('驳回原因')
    await expect(items.nth(2)).toContainText('需补充下一班次的校准确认')
    await expect(items.nth(2)).toContainText('提交人')
  })
}

test('reviewer in verifying sees the plan, completion and previous rejection, without a rejection banner', async ({ page }) => {
  const resubmitted = submission('s4', 'rectification', '2026-09-04T01:00:00Z', { stage: 'completion', comment: '二轮整改完成说明' })
  await stubFinding(page, 'compliance_review', 'verifying', [PLAN, COMPLETION, REJECTION, resubmitted])
  await page.goto('/findings/finding-history')
  await expect(history(page).getByRole('listitem')).toHaveCount(4)
  await expect(history(page)).toContainText('校准计划缺失原因')
  await expect(history(page)).toContainText('二轮整改完成说明')
  await expect(history(page)).toContainText('需补充下一班次的校准确认')
  expect(await notice(page).count()).toBe(0)
})

test('approval after a rejection hides the banner but keeps both conclusions', async ({ page }) => {
  const approved = submission('s5', 'verification', '2026-09-05T01:00:00Z', { result: 'approved' })
  await stubFinding(page, 'process_review', 'closed', [REJECTION, approved])
  await page.goto('/findings/finding-history')
  await expect(history(page).getByRole('listitem')).toHaveCount(2)
  await expect(history(page)).toContainText('验证通过')
  expect(await notice(page).count()).toBe(0)
})

test('reopened after approval: an older rejection is not shown as the latest', async ({ page }) => {
  const approved = submission('s5', 'verification', '2026-09-05T01:00:00Z', { result: 'approved' })
  await stubFinding(page, 'process_review', 'rectifying', [REJECTION, approved])
  await page.goto('/findings/finding-history')
  await expect(history(page).getByRole('listitem')).toHaveCount(2)
  expect(await notice(page).count()).toBe(0)
})

test('long text is folded and expands on demand, line breaks kept', async ({ page }) => {
  const long = Array.from({ length: 12 }, (_, i) => `第${i + 1}行整改说明`).join('\n')
  await stubFinding(page, 'process_review', 'rectifying', [
    submission('s1', 'rectification', '2026-09-01T01:00:00Z', { stage: 'plan', root_cause: long }),
  ])
  await page.goto('/findings/finding-history')
  const item = history(page).getByRole('listitem')
  await expect(item).toContainText('第1行整改说明')
  await expect(item.getByRole('button', { name: '展开' })).toBeVisible()
  await item.getByRole('button', { name: '展开' }).click()
  await expect(item.getByText('第12行整改说明')).toBeVisible()
  await expect(item.getByRole('button', { name: '收起' })).toBeVisible()
})

test('empty payload shows a plain note instead of an error', async ({ page }) => {
  await stubFinding(page, 'compliance_review', 'rectifying', [submission('s1', 'rectification', '2026-09-01T01:00:00Z', {})])
  await page.goto('/findings/finding-history')
  await expect(history(page).getByRole('listitem')).toHaveCount(1)
  await expect(history(page)).toContainText('该提交没有可显示的内容。')
})

test('unknown payload fields are shown as inert text, structures are not dumped', async ({ page }) => {
  await stubFinding(page, 'compliance_review', 'rectifying', [
    submission('s1', 'rectification', '2026-09-01T01:00:00Z', {
      stage: 'plan',
      root_cause: '原因',
      note: '<img src=x onerror="window.__xss=1"><b>bold</b>',
      nested: { secret: 'do-not-show' },
    }),
  ])
  await page.goto('/findings/finding-history')
  const item = history(page).getByRole('listitem')
  await expect(item).toContainText('其他内容（note）')
  await expect(item).toContainText('<img src=x onerror="window.__xss=1"><b>bold</b>')
  await expect(item).toContainText('此处不展示')
  expect(await item.locator('img, b').count()).toBe(0)
  expect(await item.getByText('do-not-show').count()).toBe(0)
  expect(await page.evaluate(() => (globalThis as { __xss?: number }).__xss)).toBeUndefined()
})
