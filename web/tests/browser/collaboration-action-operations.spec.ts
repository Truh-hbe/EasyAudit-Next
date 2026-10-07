import { expect, test, type Page, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'Operations User',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
}

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

interface World {
  scenarioKey: string
  action: string
  finding: string | 'error'
  caseLifecycle: string
}

async function stubAction(page: Page, world: World) {
  await page.route((url) => url.pathname === '/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...user, must_change_password: false }),
  )
  await page.route((url) => url.pathname === '/api/v1/action-items/action-ops', (route) =>
    fulfillJson(route, 200, {
      id: 'action-ops',
      organization_id: user.organization_id,
      finding_id: 'finding-ops',
      title: 'Ops Action',
      lifecycle: world.action,
      due_at: null,
      completed_at: world.action === 'done' ? '2026-10-02T00:00:00Z' : null,
    }),
  )
  await page.route((url) => url.pathname === '/api/v1/findings/finding-ops', (route) =>
    world.finding === 'error'
      ? fulfillJson(route, 500, { detail: 'boom' })
      : fulfillJson(route, 200, {
          id: 'finding-ops',
          organization_id: user.organization_id,
          case_id: 'case-ops',
          title: 'Ops Finding',
          description: null,
          severity: 'high',
          lifecycle: world.finding,
          scenario_data:
            world.scenarioKey === 'process_review'
              ? { issue_type: 'control_gap', project_category: 'assembly' }
              : { criterion_reference: '8.5.1', finding_type: 'nonconformity' },
          raised_by: user.id,
          raised_at: '2026-10-01T01:00:00Z',
        }),
  )
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-ops', (route) =>
    fulfillJson(route, 200, {
      id: 'case-ops',
      organization_id: user.organization_id,
      plan_id: null,
      scenario_key: world.scenarioKey,
      scenario_version: 1,
      title: 'Ops Case',
      lifecycle: world.caseLifecycle,
      planned_start_at: null,
      planned_end_at: null,
      started_at: '2026-10-01T00:00:00Z',
      fieldwork_completed_at: null,
      closed_at: null,
      scenario_data:
        world.scenarioKey === 'process_review'
          ? { area_code: 'A-01', review_type: 'routine' }
          : { standard_reference: 'ISO 9001', scope_summary: 'Line' },
      created_by: user.id,
      created_at: '2026-10-01T00:00:00Z',
    }),
  )
  for (const child of ['assignee-views', 'activities', 'evidences']) {
    await page.route((url) => url.pathname === `/api/v1/action-items/action-ops/${child}`, (route) =>
      fulfillJson(route, 200, []),
    )
  }
}

const WRITE_BUTTONS = ['开始整改项', '完成整改项', '重新打开整改项', '转交并重开', '取消整改项', '添加执行人']
const blockedNotice = (page: Page) => page.getByRole('status').filter({ hasText: '整改项' })

async function expectNoWriteEntries(page: Page) {
  for (const name of WRITE_BUTTONS) {
    expect(await page.getByRole('button', { name, exact: true }).count()).toBe(0)
  }
  expect(await page.getByRole('button', { name: '上传证据', exact: true }).count()).toBe(0)
  expect(await page.getByLabel('证据文件').count()).toBe(0)
}

for (const scenarioKey of ['process_review', 'compliance_review']) {
  for (const [finding, text] of [
    ['verifying', '发现项已提交验证'],
    ['closed', '发现项已关闭'],
  ] as const) {
    test(`${scenarioKey}@1: a done action under a ${finding} finding offers no write entries and explains why`, async ({ page }) => {
      await stubAction(page, { scenarioKey, action: 'done', finding, caseLifecycle: 'in_progress' })
      await page.goto('/action-items/action-ops')
      await expect(page.getByRole('heading', { level: 1 })).toHaveText('Ops Action')
      await expect(blockedNotice(page)).toContainText(text)
      await expect(blockedNotice(page).getByRole('link', { name: '返回发现项' })).toBeVisible()
      await expect(page.getByText('已上传的证据仍可查看和下载。')).toBeVisible()
      await expectNoWriteEntries(page)
    })
  }

  test(`${scenarioKey}@1: an in-progress action keeps start/complete/cancel/assign/upload under a rectifying finding`, async ({ page }) => {
    await stubAction(page, { scenarioKey, action: 'in_progress', finding: 'rectifying', caseLifecycle: 'in_progress' })
    await page.goto('/action-items/action-ops')
    await expect(page.getByRole('button', { name: '完成整改项', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '取消整改项', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '添加执行人', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '上传证据', exact: true })).toBeVisible()
    expect(await blockedNotice(page).count()).toBe(0)
  })

  test(`${scenarioKey}@1: a done action under a rectifying finding keeps reopen, transfer and evidence but not add-assignee`, async ({ page }) => {
    await stubAction(page, { scenarioKey, action: 'done', finding: 'rectifying', caseLifecycle: 'in_progress' })
    await page.goto('/action-items/action-ops')
    await expect(page.getByRole('button', { name: '重新打开整改项', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '转交并重开', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '上传证据', exact: true })).toBeVisible()
    expect(await page.getByRole('button', { name: '添加执行人', exact: true }).count()).toBe(0)
    expect(await blockedNotice(page).count()).toBe(0)
  })
}

test('a cancelled action offers no add-assignee entry', async ({ page }) => {
  await stubAction(page, { scenarioKey: 'process_review', action: 'cancelled', finding: 'rectifying', caseLifecycle: 'in_progress' })
  await page.goto('/action-items/action-ops')
  await expect(page.getByText('当前整改项已取消，没有可执行的操作。')).toBeVisible()
  expect(await page.getByRole('button', { name: '添加执行人', exact: true }).count()).toBe(0)
})

test('an inactive case closes the write entries with an explanation', async ({ page }) => {
  await stubAction(page, { scenarioKey: 'compliance_review', action: 'in_progress', finding: 'rectifying', caseLifecycle: 'closed' })
  await page.goto('/action-items/action-ops')
  await expect(blockedNotice(page)).toContainText('审查活动当前不在进行中或待关闭阶段')
  await expectNoWriteEntries(page)
})

test('when the parent finding cannot be read, commands close with an explanation and the server stays the authority for evidence', async ({ page }) => {
  await stubAction(page, { scenarioKey: 'process_review', action: 'in_progress', finding: 'error', caseLifecycle: 'in_progress' })
  await page.goto('/action-items/action-ops')
  await expect(page.getByText('无法确认所属发现项的当前状态，整改项操作已关闭；请重新加载。')).toBeVisible()
  for (const name of WRITE_BUTTONS) {
    expect(await page.getByRole('button', { name, exact: true }).count()).toBe(0)
  }
  // 证据上传不依赖场景适配器，前置条件未知时不拦截，由服务器拒绝。
  await expect(page.getByRole('button', { name: '上传证据', exact: true })).toBeVisible()
})
