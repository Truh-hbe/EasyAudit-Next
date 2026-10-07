import { expect, test, type Page, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'Wizard User',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
  must_change_password: false,
}

const catalog = [
  { scenario_key: 'process_review', scenario_version: 1, display_name: 'Process Review' },
  { scenario_key: 'compliance_review', scenario_version: 1, display_name: 'Compliance Review' },
]

const KEY_REUSE = 'Idempotency-Key reused with a different request'

type Outcome = 'abort' | 'server-error' | 'key-reuse' | 'conflict' | 'rejected' | 'dates-rejected' | 'unmapped' | 'created'

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

interface Recorded {
  key: string | null
  body: Record<string, unknown>
}

// 按顺序给每次 POST 指定结果；序列用完后一律成功。返回已记录的请求。
async function stubCreate(page: Page, path: string, outcomes: Outcome[], created: Record<string, unknown>, gate?: Promise<void>) {
  const requests: Recorded[] = []
  await page.route(`**/api/v1/${path}`, async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    requests.push({
      key: await route.request().headerValue('Idempotency-Key'),
      body: route.request().postDataJSON() as Record<string, unknown>,
    })
    if (gate !== undefined) await gate
    switch (outcomes[requests.length - 1] ?? 'created') {
      case 'abort':
        return route.abort('failed')
      case 'server-error':
        return fulfillJson(route, 500, { detail: 'Internal Server Error' })
      case 'key-reuse':
        return fulfillJson(route, 409, { detail: KEY_REUSE })
      case 'conflict':
        return fulfillJson(route, 409, { detail: 'Scenario version is no longer published' })
      case 'rejected':
        return fulfillJson(route, 422, {
          detail: 'review_type must be a non-blank string; area_code must not contain surrounding whitespace',
        })
      case 'dates-rejected':
        return fulfillJson(route, 422, {
          detail: 'planned_end_at must be greater than or equal to planned_start_at',
        })
      case 'unmapped':
        return fulfillJson(route, 422, { detail: 'Plan dates are outside the allowed range' })
      case 'created':
        return fulfillJson(route, 201, created)
    }
  })
  return requests
}

async function stubShell(page: Page) {
  await page.route('**/api/v1/me', (route) => fulfillJson(route, 200, user))
  await page.route('**/api/v1/review-catalog', (route) => fulfillJson(route, 200, catalog))
  await page.route('**/api/v1/review-plans/plan-1', (route) =>
    fulfillJson(route, 200, {
      id: 'plan-1',
      title: 'Wizard Plan',
      organization_id: user.organization_id,
      planned_start_at: '2026-08-01T00:00:00Z',
      planned_end_at: '2026-08-31T00:00:00Z',
    }),
  )
  // 创建成功后会跳到下一页，只需让它安静地加载。
  await page.route('**/api/v1/review-cases/case-1**', (route) => fulfillJson(route, 404, { detail: 'not found' }))
}

async function enterDateTime(page: Page, label: string, text: string) {
  const input = page.getByLabel(label)
  await input.fill(text)
  await input.press('Enter')
}

async function fillPlan(page: Page) {
  await page.goto('/review-plans/new')
  await page.getByLabel('计划名称').fill('向导计划')
  await enterDateTime(page, '计划开始时间（可选）', '2026/08/28 18:00')
}

async function fillCase(page: Page) {
  await page.goto('/review-plans/plan-1/review-cases/new')
  await expect(page.getByRole('heading', { name: '新建审查活动' })).toBeVisible()
  await page.getByLabel('审查活动名称').fill('向导活动')
  await page.getByLabel('区域代码').fill('area-a')
  await page.getByLabel('审查类型').fill('standard')
}

test.describe('plan step: idempotent creation', () => {
  test('double click and Enter presses share one request; the Date field Enter never submits', async ({ page }) => {
    await stubShell(page)
    let release!: () => void
    const gate = new Promise<void>((resolve) => { release = resolve })
    const requests = await stubCreate(page, 'review-plans', [], { id: 'plan-1', title: '向导计划' }, gate)
    await page.goto('/review-plans/new')
    await page.getByLabel('计划名称').fill('向导计划')
    await enterDateTime(page, '计划开始时间（可选）', '2026/08/28 18:00')
    await page.waitForTimeout(300)
    expect(requests).toHaveLength(0)

    await page.getByRole('button', { name: '保存计划并继续' }).dblclick()
    await expect(page.getByRole('button', { name: '正在保存计划…' })).toBeVisible()
    expect(requests).toHaveLength(1)
    release()
    await expect(page).toHaveURL(/\/review-plans\/plan-1\/review-cases\/new$/)
    expect(requests).toHaveLength(1)
  })

  test('Enter pressed twice in the title field creates once', async ({ page }) => {
    await stubShell(page)
    let release!: () => void
    const gate = new Promise<void>((resolve) => { release = resolve })
    const requests = await stubCreate(page, 'review-plans', [], { id: 'plan-1', title: '向导计划' }, gate)
    await page.goto('/review-plans/new')
    const title = page.getByLabel('计划名称')
    await title.fill('向导计划')
    await title.press('Enter')
    await title.press('Enter')
    await expect.poll(() => requests.length).toBe(1)
    await page.waitForTimeout(300)
    expect(requests).toHaveLength(1)
    release()
    await expect(page).toHaveURL(/\/review-plans\/plan-1\/review-cases\/new$/)
  })

  for (const outcome of ['abort', 'server-error'] as const) {
    test(`unknown outcome (${outcome}): says it is unconfirmed, keeps draft and key, checks in a new tab, never replays by itself`, async ({ page }) => {
      await stubShell(page)
      const requests = await stubCreate(page, 'review-plans', [outcome], { id: 'plan-1', title: '向导计划' })
      await fillPlan(page)
      await page.getByRole('button', { name: '保存计划并继续' }).click()

      await expect(page.getByRole('alert').filter({ hasText: '未确认是否成功' })).toBeVisible()
      await expect(page.getByLabel('计划名称')).toHaveValue('向导计划')
      await expect(page.getByLabel('计划开始时间（可选）')).toHaveValue('2026/08/28 18:00')
      await page.waitForTimeout(1500)
      expect(requests).toHaveLength(1)

      // 核对入口在新标签页打开，本页保持挂载：草稿和键都还在。
      const check = page.getByRole('link', { name: '在新标签页核对审查活动' })
      await expect(check).toHaveAttribute('target', '_blank')
      await expect(check).toHaveAttribute('rel', /noopener/)
      const opened = page.context().waitForEvent('page')
      await check.click()
      const checkPage = await opened
      await checkPage.waitForURL(/\/review-cases$/)
      await checkPage.close()
      await expect(page.getByLabel('计划名称')).toHaveValue('向导计划')
      await expect(page.getByLabel('计划开始时间（可选）')).toHaveValue('2026/08/28 18:00')
      expect(requests).toHaveLength(1)
      await page.getByRole('button', { name: '重试保存计划' }).click()
      await expect(page).toHaveURL(/\/review-plans\/plan-1\/review-cases\/new$/)
      expect(requests).toHaveLength(2)
      expect(requests[0].key).toBeTruthy()
      expect(requests[1].key).toBe(requests[0].key)
      expect(requests[1].body).toEqual(requests[0].body)
    })
  }

  test('409 key reuse: says the content differs, keeps the draft, does not rotate the key', async ({ page }) => {
    await stubShell(page)
    const requests = await stubCreate(page, 'review-plans', ['abort', 'key-reuse'], { id: 'plan-1', title: '向导计划' })
    await fillPlan(page)
    await page.getByRole('button', { name: '保存计划并继续' }).click()
    await expect(page.getByRole('button', { name: '重试保存计划' })).toBeEnabled()
    await page.getByLabel('计划名称').fill('向导计划（已修改）')
    await page.getByRole('button', { name: '重试保存计划' }).click()

    await expect(page.getByRole('alert')).toContainText('当前内容与之前提交的创建请求不一致')
    await expect(page.getByRole('alert')).toContainText('刷新')
    await expect(page.getByLabel('计划名称')).toHaveValue('向导计划（已修改）')
    await page.getByRole('button', { name: '重试保存计划' }).click()
    await expect.poll(() => requests.length).toBe(3)
    expect(new Set(requests.map((request) => request.key)).size).toBe(1)
  })

  test('other 409 conflicts show a business message, not the key reuse message', async ({ page }) => {
    await stubShell(page)
    await stubCreate(page, 'review-plans', ['conflict'], { id: 'plan-1', title: '向导计划' })
    await fillPlan(page)
    await page.getByRole('button', { name: '保存计划并继续' }).click()
    const alert = page.getByRole('alert')
    await expect(alert).toContainText('Scenario version is no longer published')
    await expect(alert).not.toContainText('不一致')
    await expect(page.getByLabel('计划名称')).toHaveValue('向导计划')
  })

  test('422 that names a field is shown on that field and focuses it; other 422 uses an Alert', async ({ page }) => {
    await stubShell(page)
    await page.route('**/api/v1/review-plans', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      const mapped = (route.request().postDataJSON() as { title: string }).title === '向导计划'
      return fulfillJson(route, 422, {
        detail: mapped ? 'planned_start_at must be a valid time' : 'Plan dates are outside the allowed range',
      })
    })
    await fillPlan(page)
    await page.getByRole('button', { name: '保存计划并继续' }).click()
    await expect(page.getByText('planned_start_at must be a valid time')).toBeVisible()
    await expect(page.getByLabel('计划开始时间（可选）')).toBeFocused()
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect(page.getByLabel('计划名称')).toHaveValue('向导计划')

    // 修改该字段后字段提示消失。
    await enterDateTime(page, '计划开始时间（可选）', '2026/08/29 18:00')
    await expect(page.getByText('planned_start_at must be a valid time')).toHaveCount(0)

    await page.getByLabel('计划名称').fill('另一个计划')
    await page.getByRole('button', { name: '重试保存计划' }).click()
    await expect(page.getByRole('alert')).toHaveText('Plan dates are outside the allowed range')
    await expect(page.getByLabel('计划名称')).toHaveValue('另一个计划')
  })
})

test.describe('plan step: dates are Asia/Shanghai wall time on any device', () => {
  const zones = ['America/New_York', 'Asia/Shanghai', 'Pacific/Auckland']
  for (const timezoneId of zones) {
    test.describe(timezoneId, () => {
      test.use({ timezoneId })

      test('typed times, device DST gaps and invalid text', async ({ page }) => {
        await stubShell(page)
        const requests = await stubCreate(page, 'review-plans', [], { id: 'plan-1', title: '时区计划' })
        await page.goto('/review-plans/new')
        const start = page.getByLabel('计划开始时间（可选）')
        await page.getByLabel('计划名称').fill('时区计划')
        const submit = page.getByRole('button', { name: /保存计划并继续|重试保存计划/ })

        // 2026-03-08 02:30 落在美国夏令时的空洞里，但它是存在的上海时间：不能被设备时区吞掉或改成 03:30。
        await enterDateTime(page, '计划开始时间（可选）', '2026/03/08 02:30')
        await expect(start).toHaveValue('2026/03/08 02:30')
        // 上海 1986-05-04 02:30 不存在（夏令时跳过）：无论设备在哪个时区都拒绝，不静默改成 03:30。
        await enterDateTime(page, '计划结束时间（可选）', '1986/05/04 02:30')
        await submit.click()
        await expect(page.getByText('计划结束时间无效：请填写存在的上海时间（Asia/Shanghai）。')).toBeVisible()
        expect(requests).toHaveLength(0)

        // 越界日期：不能被当作"未填写"提交，也不能静默回退为旧值。
        await enterDateTime(page, '计划结束时间（可选）', '2026/02/30 10:00')
        await submit.click()
        await expect(page.getByText('计划结束时间无效：请填写存在的上海时间（Asia/Shanghai）。')).toBeVisible()
        expect(requests).toHaveLength(0)

        // 只键入、不按 Enter 就离开输入框，同样按键入的文本校验。
        await page.getByLabel('计划结束时间（可选）').fill('2026/13/01 10:00')
        await page.getByLabel('计划结束时间（可选）').press('Tab')
        await submit.click()
        await expect(page.getByText('计划结束时间无效：请填写存在的上海时间（Asia/Shanghai）。')).toBeVisible()
        expect(requests).toHaveLength(0)

        await enterDateTime(page, '计划结束时间（可选）', '2026/03/09 09:30')
        await submit.click()
        await expect.poll(() => requests.length).toBe(1)
        expect(requests[0].body).toMatchObject({
          planned_start_at: '2026-03-07T18:30:00.000Z',
          planned_end_at: '2026-03-09T01:30:00.000Z',
        })
      })
    })
  }
})

// 面板的时间列是 list：分钟列含 59，小时列含 23 但不含 59。
async function pickPanelTime(page: Page, hour: string, minute: string) {
  const hours = page.getByRole('list').filter({ hasText: '23' }).filter({ hasNotText: '59' })
  const minutes = page.getByRole('list').filter({ hasText: '59' })
  await hours.getByText(hour, { exact: true }).click()
  await minutes.getByText(minute, { exact: true }).click()
}

test.describe('plan step: calendar panel is Asia/Shanghai wall time on any device', () => {
  for (const timezoneId of ['America/New_York', 'Asia/Shanghai', 'Pacific/Auckland']) {
    test.describe(timezoneId, () => {
      test.use({ timezoneId })

      test('"此刻" is the current Shanghai wall time, whatever the device zone', async ({ page }) => {
        // 同一个真实时刻：上海 2026-08-28 10:30（UTC 02:30）。
        await page.clock.setFixedTime(new Date('2026-08-28T10:30:00+08:00'))
        await stubShell(page)
        const requests = await stubCreate(page, 'review-plans', [], { id: 'plan-1', title: '面板计划' })
        await page.goto('/review-plans/new')
        await page.getByLabel('计划名称').fill('面板计划')
        await page.getByLabel('计划开始时间（可选）').click()
        await page.getByText('此刻').click()
        await expect(page.getByLabel('计划开始时间（可选）')).toHaveValue('2026/08/28 10:30')
        await page.getByRole('button', { name: '保存计划并继续' }).click()
        await expect.poll(() => requests.length).toBe(1)
        expect(requests[0].body).toMatchObject({ planned_start_at: '2026-08-28T02:30:00.000Z' })
      })

      test('picking from the panel on an empty field, including a device DST gap time', async ({ page }) => {
        await page.clock.setFixedTime(new Date('2026-03-05T12:00:00+08:00'))
        await stubShell(page)
        const requests = await stubCreate(page, 'review-plans', [], { id: 'plan-1', title: '面板计划' })
        await page.goto('/review-plans/new')
        await page.getByLabel('计划名称').fill('面板计划')
        await page.getByLabel('计划开始时间（可选）').click()
        // 2026-03-08 02:30 落在美国夏令时空洞里；面板不能把它改成 03:30。
        await page.getByTitle('2026-03-08').click()
        await pickPanelTime(page, '02', '30')
        await page.getByRole('button', { name: '确 定' }).click()
        await expect(page.getByLabel('计划开始时间（可选）')).toHaveValue('2026/03/08 02:30')
        await page.getByRole('button', { name: '保存计划并继续' }).click()
        await expect.poll(() => requests.length).toBe(1)
        expect(requests[0].body).toMatchObject({ planned_start_at: '2026-03-07T18:30:00.000Z' })
      })

      test('picking from the panel on a field that already has a value', async ({ page }) => {
        await stubShell(page)
        const requests = await stubCreate(page, 'review-plans', [], { id: 'plan-1', title: '面板计划' })
        await page.goto('/review-plans/new')
        await page.getByLabel('计划名称').fill('面板计划')
        await enterDateTime(page, '计划开始时间（可选）', '2026/03/08 18:00')
        await page.getByLabel('计划开始时间（可选）').click()
        await pickPanelTime(page, '02', '30')
        await page.getByRole('button', { name: '确 定' }).click()
        await expect(page.getByLabel('计划开始时间（可选）')).toHaveValue('2026/03/08 02:30')
        await page.getByRole('button', { name: '保存计划并继续' }).click()
        await expect.poll(() => requests.length).toBe(1)
        expect(requests[0].body).toMatchObject({ planned_start_at: '2026-03-07T18:30:00.000Z' })
      })
    })
  }
})

test.describe('plan step: invalid date text is never cleared or rewritten', () => {
  test('the typed text stays through blur, refocus and submit; fixing it clears the error and syncs the panel', async ({ page }) => {
    await stubShell(page)
    const requests = await stubCreate(page, 'review-plans', [], { id: 'plan-1', title: '向导计划' })
    await page.goto('/review-plans/new')
    await page.getByLabel('计划名称').fill('向导计划')
    const end = page.getByLabel('计划结束时间（可选）')
    const message = page.getByText('计划结束时间无效：请填写存在的上海时间（Asia/Shanghai）。')
    for (const text of ['2026/02/30 10:00', '2026/08/28 12:99']) {
      await end.fill(text)
      await end.press('Tab')
      await expect(end).toHaveValue(text)
      await expect(message).toBeVisible()
      await end.focus()
      await expect(end).toHaveValue(text)
      await page.getByRole('button', { name: '保存计划并继续' }).click()
      await expect(end).toHaveValue(text)
      await expect(message).toBeVisible()
      await expect(end).toBeFocused()
      expect(requests).toHaveLength(0)
    }

    await enterDateTime(page, '计划结束时间（可选）', '2026/08/28 18:00')
    await expect(message).toHaveCount(0)
    // 面板已同步到新的有效值：只改小时，日期和分钟沿用。
    await end.click()
    await pickPanelTime(page, '09', '00')
    await page.getByRole('button', { name: '确 定' }).click()
    await expect(end).toHaveValue('2026/08/28 09:00')
    await page.getByRole('button', { name: '保存计划并继续' }).click()
    await expect.poll(() => requests.length).toBe(1)
    expect(requests[0].body).toMatchObject({ planned_end_at: '2026-08-28T01:00:00.000Z' })
  })

  for (const timezoneId of ['America/New_York', 'Asia/Shanghai', 'Pacific/Auckland']) {
    test.describe(timezoneId, () => {
      test.use({ timezoneId })

      test('valid value → invalid text → re-picking the same valid value from the panel recovers', async ({ page }) => {
        await stubShell(page)
        const requests = await stubCreate(page, 'review-plans', [], { id: 'plan-1', title: '向导计划' })
        await page.goto('/review-plans/new')
        await page.getByLabel('计划名称').fill('向导计划')
        const start = page.getByLabel('计划开始时间（可选）')
        const message = page.getByText('计划开始时间无效：请填写存在的上海时间（Asia/Shanghai）。')
        await enterDateTime(page, '计划开始时间（可选）', '2026/08/28 18:00')
        await start.fill('2026/02/30 10:00')
        await start.press('Tab')
        await expect(start).toHaveValue('2026/02/30 10:00')
        await expect(message).toBeVisible()

        await start.click()
        await pickPanelTime(page, '18', '00')
        await page.getByRole('button', { name: '确 定' }).click()
        await expect(start).toHaveValue('2026/08/28 18:00')
        await expect(message).toHaveCount(0)
        await page.getByRole('button', { name: '保存计划并继续' }).click()
        await expect.poll(() => requests.length).toBe(1)
        expect(requests[0].body).toMatchObject({ planned_start_at: '2026-08-28T10:00:00.000Z' })
      })
    })
  }

  test('the error keeps the time zone hint in the accessible description', async ({ page }) => {
    await stubShell(page)
    await page.goto('/review-plans/new')
    await page.getByLabel('计划名称').fill('向导计划')
    const start = page.getByLabel('计划开始时间（可选）')
    await expect(start).toHaveAccessibleDescription('以下时间均按上海时间（Asia/Shanghai）填写和显示。')
    await enterDateTime(page, '计划开始时间（可选）', '1986/05/04 02:30')
    await page.getByRole('button', { name: '保存计划并继续' }).click()
    await expect(start).toHaveAccessibleDescription(/无效/)
    await expect(start).toHaveAccessibleDescription(/以下时间均按上海时间/)
  })
})

test.describe('case step', () => {
  test('recovers from a reload and lists scenarios as radios with Chinese names', async ({ page }) => {
    await stubShell(page)
    await page.goto('/review-plans/plan-1/review-cases/new')
    await expect(page.getByRole('heading', { name: '新建审查活动' })).toBeVisible()
    await expect(page.getByText('Wizard Plan')).toBeVisible()
    const radios = page.getByRole('radio')
    await expect(radios).toHaveCount(2)
    await expect(page.getByRole('radio', { name: /过程审查/ })).toBeChecked()
    await page.getByRole('radio', { name: /compliance_review@1/ }).check()
    await expect(page.getByLabel('标准 / 依据')).toBeVisible()
    await expect(page.getByLabel('区域代码')).toHaveCount(0)
    await page.reload()
    await expect(page.getByRole('heading', { name: '新建审查活动' })).toBeVisible()
  })

  test('more than four scenarios are chosen with a Select', async ({ page }) => {
    await stubShell(page)
    await page.route('**/api/v1/review-catalog', (route) =>
      fulfillJson(route, 200, [
        ...catalog,
        ...[2, 3, 4].map((version) => ({ scenario_key: 'process_review', scenario_version: version, display_name: 'Process' })),
      ]),
    )
    await page.goto('/review-plans/plan-1/review-cases/new')
    await expect(page.getByRole('heading', { name: '新建审查活动' })).toBeVisible()
    await expect(page.getByRole('radio')).toHaveCount(0)
    await expect(page.getByLabel('审查场景')).toBeVisible()
  })

  test('double click creates once; unknown outcome keeps draft and key; retry reuses the key', async ({ page }) => {
    await stubShell(page)
    const requests = await stubCreate(page, 'review-cases', ['abort'], { id: 'case-1' })
    await fillCase(page)
    await page.getByRole('button', { name: '创建审查活动' }).dblclick()
    await expect(page.getByRole('alert').filter({ hasText: '未确认是否成功' })).toBeVisible()
    expect(requests).toHaveLength(1)
    await page.waitForTimeout(1500)
    expect(requests).toHaveLength(1)
    await expect(page.getByLabel('审查活动名称')).toHaveValue('向导活动')
    await expect(page.getByLabel('区域代码')).toHaveValue('area-a')

    // 核对入口在新标签页打开，本页保持挂载：草稿和键都还在。
    const check = page.getByRole('link', { name: '在新标签页核对是否已创建' })
    await expect(check).toHaveAttribute('target', '_blank')
    await expect(check).toHaveAttribute('rel', /noopener/)
    const opened = page.context().waitForEvent('page')
    await check.click()
    const checkPage = await opened
    await checkPage.waitForURL(/\/review-cases$/)
    await checkPage.close()
    await expect(page.getByLabel('审查活动名称')).toHaveValue('向导活动')
    expect(requests).toHaveLength(1)

    await page.getByRole('button', { name: '重试创建审查活动' }).click()
    await expect(page).toHaveURL(/\/review-cases\/case-1$/)
    expect(requests).toHaveLength(2)
    expect(requests[1].key).toBe(requests[0].key)
    expect(requests[1].body).toEqual(requests[0].body)
  })

  test('5xx is an unknown outcome as well', async ({ page }) => {
    await stubShell(page)
    const requests = await stubCreate(page, 'review-cases', ['server-error'], { id: 'case-1' })
    await fillCase(page)
    await page.getByRole('button', { name: '创建审查活动' }).click()
    await expect(page.getByRole('alert')).toContainText('未确认是否成功')
    await expect(page.getByRole('button', { name: '重试创建审查活动' })).toBeEnabled()
    expect(requests).toHaveLength(1)
  })

  test('409 key reuse keeps the draft and the key; other 409 shows the business message', async ({ page }) => {
    await stubShell(page)
    const requests = await stubCreate(page, 'review-cases', ['key-reuse', 'conflict'], { id: 'case-1' })
    await fillCase(page)
    await page.getByRole('button', { name: '创建审查活动' }).click()
    await expect(page.getByRole('alert')).toContainText('当前内容与之前提交的创建请求不一致')
    await expect(page.getByLabel('审查活动名称')).toHaveValue('向导活动')
    await page.getByRole('button', { name: '创建审查活动' }).click()
    await expect(page.getByRole('alert')).toContainText('Scenario version is no longer published')
    await expect(page.getByRole('alert')).not.toContainText('不一致')
    expect(requests).toHaveLength(2)
    expect(requests[1].key).toBe(requests[0].key)
  })

  test('422 on scenario fields lands on those fields, focuses the first one and keeps the draft', async ({ page }) => {
    await stubShell(page)
    const requests = await stubCreate(page, 'review-cases', ['rejected'], { id: 'case-1' })
    await fillCase(page)
    await page.getByRole('button', { name: '创建审查活动' }).click()
    await expect(page.getByText('review_type must be a non-blank string')).toBeVisible()
    await expect(page.getByText('area_code must not contain surrounding whitespace')).toBeVisible()
    // 按适配器的字段顺序，第一个有错的字段是区域代码。
    await expect(page.getByLabel('区域代码')).toBeFocused()
    // 错误文案关联到输入框，读屏能读到。
    const area = page.getByLabel('区域代码')
    await expect(area).toHaveAttribute('aria-invalid', 'true')
    await expect(area).toHaveAccessibleDescription('area_code must not contain surrounding whitespace')
    await expect(page.getByLabel('审查类型')).toHaveAttribute('aria-invalid', 'true')
    await expect(page.getByLabel('审查类型')).toHaveAccessibleDescription('review_type must be a non-blank string')
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect(page.getByLabel('审查活动名称')).toHaveValue('向导活动')

    await page.getByLabel('区域代码').fill('area-b')
    await expect(page.getByText('area_code must not contain surrounding whitespace')).toHaveCount(0)
    await expect(area).not.toHaveAttribute('aria-invalid', 'true')
    await page.getByRole('button', { name: '创建审查活动' }).click()
    await expect.poll(() => requests.length).toBe(2)
    expect(requests[1].key).toBe(requests[0].key)
  })

  test('422 without a field falls back to an Alert', async ({ page }) => {
    await stubShell(page)
    await stubCreate(page, 'review-cases', ['unmapped'], { id: 'case-1' })
    await fillCase(page)
    await page.getByRole('button', { name: '创建审查活动' }).click()
    await expect(page.getByRole('alert')).toHaveText('Plan dates are outside the allowed range')
  })

  test('dates are optional: left empty they are omitted, never copied from the plan', async ({ page }) => {
    await stubShell(page)
    const requests = await stubCreate(page, 'review-cases', [], { id: 'case-1' })
    await fillCase(page)
    // 计划日期只读展示，不会预填到活动日期。
    await expect(page.getByText('2026/08/01 08:00')).toBeVisible()
    await expect(page.getByLabel('活动开始时间（可选）')).toHaveValue('')
    await expect(page.getByLabel('活动结束时间（可选）')).toHaveValue('')
    await page.getByRole('button', { name: '创建审查活动' }).click()
    await expect(page).toHaveURL(/\/review-cases\/case-1$/)
    expect(requests[0].body).not.toHaveProperty('planned_start_at')
    expect(requests[0].body).not.toHaveProperty('planned_end_at')
  })

  test('filled dates are sent as Asia/Shanghai ISO instants; a lone end date is allowed', async ({ page }) => {
    await stubShell(page)
    const requests = await stubCreate(page, 'review-cases', [], { id: 'case-1' })
    await fillCase(page)
    await enterDateTime(page, '活动开始时间（可选）', '2026/09/01 09:00')
    await enterDateTime(page, '活动结束时间（可选）', '2026/09/30 18:00')
    await page.getByRole('button', { name: '创建审查活动' }).click()
    await expect(page).toHaveURL(/\/review-cases\/case-1$/)
    expect(requests[0].body).toMatchObject({
      planned_start_at: '2026-09-01T01:00:00.000Z',
      planned_end_at: '2026-09-30T10:00:00.000Z',
    })

    await fillCase(page)
    await enterDateTime(page, '活动结束时间（可选）', '2026/09/30 18:00')
    await page.getByRole('button', { name: '创建审查活动' }).click()
    await expect.poll(() => requests.length).toBe(2)
    expect(requests[1].body).not.toHaveProperty('planned_start_at')
    expect(requests[1].body).toMatchObject({ planned_end_at: '2026-09-30T10:00:00.000Z' })
  })

  test('invalid text or an end before the start is rejected on the field without a request', async ({ page }) => {
    await stubShell(page)
    const requests = await stubCreate(page, 'review-cases', [], { id: 'case-1' })
    await fillCase(page)
    await enterDateTime(page, '活动开始时间（可选）', '2026/02/30 10:00')
    await page.getByRole('button', { name: '创建审查活动' }).click()
    await expect(page.getByText('活动开始时间无效：请填写存在的上海时间（Asia/Shanghai）。')).toBeVisible()
    expect(requests).toHaveLength(0)

    await enterDateTime(page, '活动开始时间（可选）', '2026/09/30 18:00')
    await enterDateTime(page, '活动结束时间（可选）', '2026/09/01 09:00')
    await page.getByRole('button', { name: '创建审查活动' }).click()
    await expect(page.getByText('活动结束时间不能早于计划开始时间。')).toBeVisible()
    await expect(page.getByLabel('活动结束时间（可选）')).toBeFocused()
    expect(requests).toHaveLength(0)
    await expect(page.getByLabel('审查活动名称')).toHaveValue('向导活动')

    // 改开始时间后，结束时间的错误随之重新校验。
    await enterDateTime(page, '活动开始时间（可选）', '2026/08/30 18:00')
    await page.getByRole('button', { name: '创建审查活动' }).click()
    await expect(page).toHaveURL(/\/review-cases\/case-1$/)
    expect(requests).toHaveLength(1)
  })

  test('422 on the dates lands on the end field, keeps the dates and the key; the retry sends the same dates', async ({ page }) => {
    await stubShell(page)
    const requests = await stubCreate(page, 'review-cases', ['dates-rejected'], { id: 'case-1' })
    await fillCase(page)
    await enterDateTime(page, '活动开始时间（可选）', '2026/09/01 09:00')
    await enterDateTime(page, '活动结束时间（可选）', '2026/09/30 18:00')
    await page.getByRole('button', { name: '创建审查活动' }).click()
    const end = page.getByLabel('活动结束时间（可选）')
    await expect(page.getByText('planned_end_at must be greater than or equal to planned_start_at')).toBeVisible()
    await expect(end).toBeFocused()
    await expect(end).toHaveAccessibleDescription(/planned_end_at must be greater than or equal to planned_start_at/)
    await expect(page.getByLabel('活动开始时间（可选）')).toHaveValue('2026/09/01 09:00')
    await expect(end).toHaveValue('2026/09/30 18:00')
    await expect(page.getByRole('alert')).toHaveCount(0)

    // 修改字段后错误清除；服务器明确拒绝过，重试沿用同一键（拒绝不会占用键）。
    await enterDateTime(page, '活动结束时间（可选）', '2026/10/01 18:00')
    await expect(page.getByText('planned_end_at must be')).toHaveCount(0)
    await page.getByRole('button', { name: '创建审查活动' }).click()
    await expect(page).toHaveURL(/\/review-cases\/case-1$/)
    expect(requests[1].body).toMatchObject({
      planned_start_at: '2026-09-01T01:00:00.000Z',
      planned_end_at: '2026-10-01T10:00:00.000Z',
    })
  })

  test('unknown outcome with dates: the retry sends the same key and the same dates', async ({ page }) => {
    await stubShell(page)
    const requests = await stubCreate(page, 'review-cases', ['abort'], { id: 'case-1' })
    await fillCase(page)
    await enterDateTime(page, '活动开始时间（可选）', '2026/09/01 09:00')
    await enterDateTime(page, '活动结束时间（可选）', '2026/09/30 18:00')
    await page.getByRole('button', { name: '创建审查活动' }).click()
    await expect(page.getByRole('alert').filter({ hasText: '未确认是否成功' })).toBeVisible()
    await expect(page.getByLabel('活动结束时间（可选）')).toHaveValue('2026/09/30 18:00')
    await page.getByRole('button', { name: '重试创建审查活动' }).click()
    await expect(page).toHaveURL(/\/review-cases\/case-1$/)
    expect(requests).toHaveLength(2)
    expect(requests[1].key).toBe(requests[0].key)
    expect(requests[1].body).toEqual(requests[0].body)
    expect(requests[1].body).toMatchObject({ planned_end_at: '2026-09-30T10:00:00.000Z' })
  })

  test('a blank or padded name is rejected on the field without a request', async ({ page }) => {
    await stubShell(page)
    const requests = await stubCreate(page, 'review-cases', [], { id: 'case-1' })
    await fillCase(page)
    await page.getByLabel('审查活动名称').fill(' 前后有空格 ')
    await page.getByRole('button', { name: '创建审查活动' }).click()
    await expect(page.getByText('审查活动名称前后不能有空格。')).toBeVisible()
    await expect(page.getByLabel('审查活动名称')).toBeFocused()
    expect(requests).toHaveLength(0)
  })
})

test.describe('narrow screens', () => {
  for (const width of [375, 320]) {
    test(`both steps have no horizontal overflow at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 })
      await stubShell(page)
      const overflows = () =>
        page.evaluate(() => {
          const root = globalThis as unknown as { document: { documentElement: { scrollWidth: number; clientWidth: number } } }
          return root.document.documentElement.scrollWidth > root.document.documentElement.clientWidth
        })
      await page.goto('/review-plans/new')
      await expect(page.getByRole('heading', { name: '新建审查计划' })).toBeVisible()
      expect(await overflows()).toBe(false)
      await page.goto('/review-plans/plan-1/review-cases/new')
      await expect(page.getByRole('heading', { name: '新建审查活动' })).toBeVisible()
      await expect(page.getByText('Wizard Plan')).toBeVisible()
      expect(await overflows()).toBe(false)
    })
  }
})
