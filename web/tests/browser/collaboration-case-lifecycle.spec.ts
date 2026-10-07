import { expect, test, type Page, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'Lifecycle User',
  platform_role: 'ordinary_user',
  primary_department_id: null,
  is_active: true,
}

type Scenario = 'process_review' | 'compliance_review'
const SCENARIOS: Scenario[] = ['process_review', 'compliance_review']
const CASE_ID = 'case-lifecycle'

// 各 lifecycle 下命令的状态机预期：[按钮名, action]。
const NEXT: Record<string, Record<string, string>> = {
  schedule: { from: 'draft', to: 'scheduled' },
  start: { from: 'scheduled', to: 'in_progress' },
  finish_fieldwork: { from: 'in_progress', to: 'awaiting_closure' },
  close: { from: 'awaiting_closure', to: 'closed' },
  cancel: { from: 'draft', to: 'cancelled' },
  reopen_fieldwork: { from: 'awaiting_closure', to: 'in_progress' },
}

interface Command {
  action: string
  button: string
  // confirm 对应的确认框标题与确认按钮；reason 对应的弹层。
  dialog?: { title: string; ok: string }
  // 需要原因的命令：弹层里的原因输入框标签。
  reasonLabel?: string
}

const COMMANDS: Command[] = [
  { action: 'schedule', button: '安排活动' },
  { action: 'start', button: '开始活动' },
  { action: 'finish_fieldwork', button: '完成现场工作', dialog: { title: '完成现场工作', ok: '确认完成' } },
  { action: 'close', button: '关闭活动', dialog: { title: '关闭活动', ok: '确认关闭' } },
  { action: 'cancel', button: '取消活动', dialog: { title: '取消活动', ok: '确认取消' }, reasonLabel: '取消原因' },
  { action: 'reopen_fieldwork', button: '恢复现场', dialog: { title: '恢复现场', ok: '确认恢复' }, reasonLabel: '恢复原因' },
]

interface World {
  scenario: Scenario
  lifecycle: string
  posts: { action: string; reason: string | null }[]
  caseReads: number
  // 命令的响应：200 以外的状态；'abort' 表示连接中断；gate 在响应前挂起。
  postStatus: number | 'abort'
  postDetail: string
  gate: Promise<void> | null
  caseStatus: number
  // 命令失败后“别人已改变了状态”：下一次读取返回的 lifecycle。
  lifecycleAfterFailure: string | null
}

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

function caseBody(world: World) {
  return {
    id: CASE_ID,
    organization_id: user.organization_id,
    plan_id: null,
    scenario_key: world.scenario,
    scenario_version: 1,
    title: 'Lifecycle Case',
    lifecycle: world.lifecycle,
    planned_start_at: null,
    planned_end_at: null,
    started_at: null,
    fieldwork_completed_at: null,
    closed_at: null,
    scenario_data:
      world.scenario === 'process_review'
        ? { area_code: 'A-01', review_type: 'routine' }
        : { standard_reference: 'ISO 9001', scope_summary: 'Line' },
    created_by: user.id,
    created_at: '2026-08-18T00:00:00Z',
  }
}

async function mockWorld(page: Page, scenario: Scenario, lifecycle: string): Promise<World> {
  const world: World = {
    scenario,
    lifecycle,
    posts: [],
    caseReads: 0,
    postStatus: 200,
    postDetail: '',
    gate: null,
    caseStatus: 200,
    lifecycleAfterFailure: null,
  }
  await page.route((url) => url.pathname === '/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...user, must_change_password: false }),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${CASE_ID}`, (route) => {
    world.caseReads += 1
    return world.caseStatus === 200
      ? fulfillJson(route, 200, caseBody(world))
      : fulfillJson(route, world.caseStatus, { detail: 'x' })
  })
  for (const child of ['findings', 'activities']) {
    await page.route((url) => url.pathname === `/api/v1/review-cases/${CASE_ID}/${child}`, (route) =>
      fulfillJson(route, 200, []),
    )
  }
  await page.route((url) => url.pathname === `/api/v1/review-cases/${CASE_ID}/members`, (route) =>
    fulfillJson(route, 200, [
      { case_id: CASE_ID, user_id: user.id, role_key: 'lead', joined_at: '2026-08-18T00:00:00Z', display_name: 'Lifecycle User' },
    ]),
  )
  await page.route((url) => url.pathname === `/api/v1/management/review-cases/${CASE_ID}/progress`, (route) =>
    fulfillJson(route, 404, { detail: 'Not found' }),
  )
  await page.route((url) => url.pathname === `/api/v1/review-cases/${CASE_ID}/transitions`, async (route) => {
    const body = route.request().postDataJSON() as { action: string; reason: string | null }
    world.posts.push(body)
    await world.gate
    if (world.postStatus === 'abort') return route.abort('failed')
    if (world.postStatus !== 200) {
      if (world.lifecycleAfterFailure !== null) world.lifecycle = world.lifecycleAfterFailure
      return fulfillJson(route, world.postStatus, { detail: world.postDetail })
    }
    world.lifecycle = NEXT[body.action]?.to ?? world.lifecycle
    return fulfillJson(route, 200, caseBody(world))
  })
  return world
}

const commands = (page: Page) => page.getByRole('region', { name: '活动操作' })
const header = (page: Page) => page.getByRole('article').locator('header')
const button = (page: Page, name: string) => commands(page).getByRole('button', { name, exact: true })

async function open(page: Page) {
  await page.goto(`/review-cases/${CASE_ID}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Lifecycle Case' })).toBeVisible()
}

// 触发命令；confirm / reason 类型走各自弹层。reason 命令填入原因后提交。
async function invoke(page: Page, command: Command) {
  await button(page, command.button).click()
  if (command.dialog === undefined) return
  const dialog = page.getByRole('dialog', { name: command.dialog.title })
  if (command.reasonLabel !== undefined) await dialog.getByLabel(command.reasonLabel).fill('计划调整')
  await dialog.getByRole('button', { name: command.dialog.ok }).click()
}

for (const scenario of SCENARIOS) {
  test.describe(scenario, () => {
    test('walks draft → scheduled → in_progress → awaiting_closure → closed, showing only the commands the state allows', async ({ page }) => {
      const world = await mockWorld(page, scenario, 'draft')
      await open(page)

      // draft：只有安排/取消；没有开始、完成、关闭，也没有发现项录入表单。
      await expect(button(page, '安排活动')).toBeVisible()
      await expect(button(page, '取消活动')).toBeVisible()
      for (const hidden of ['开始活动', '完成现场工作', '关闭活动']) expect(await button(page, hidden).count()).toBe(0)
      await expect(page.getByText('后才能新建发现项')).toBeVisible()
      expect(await page.getByRole('button', { name: '新建发现项' }).count()).toBe(0)

      await invoke(page, COMMANDS[0])
      await expect(header(page).getByText('已排期', { exact: true })).toBeVisible()
      await expect(button(page, '开始活动')).toBeVisible()
      expect(await button(page, '安排活动').count()).toBe(0)

      await invoke(page, COMMANDS[1])
      await expect(header(page).getByText('审查中', { exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: '新建发现项' })).toBeVisible()
      expect(await button(page, '取消活动').count()).toBe(0)

      // 完成现场工作：确认前不发请求。
      await button(page, '完成现场工作').click()
      await expect(page.getByRole('dialog', { name: '完成现场工作' })).toBeVisible()
      expect(world.posts.map((post) => post.action)).toEqual(['schedule', 'start'])
      await page.getByRole('dialog', { name: '完成现场工作' }).getByRole('button', { name: '确认完成' }).click()
      await expect(header(page).getByText('待关闭', { exact: true })).toBeVisible()
      expect(await page.getByRole('button', { name: '新建发现项' }).count()).toBe(0)

      await invoke(page, COMMANDS[3])
      await expect(header(page).getByText('已关闭', { exact: true })).toBeVisible()
      await expect(commands(page).getByText('当前状态没有可执行的操作')).toBeVisible()

      expect(world.posts).toEqual([
        { action: 'schedule', reason: null },
        { action: 'start', reason: null },
        { action: 'finish_fieldwork', reason: null },
        { action: 'close', reason: null },
      ])
    })

    test('reopen_fieldwork asks for a reason, returns to in_progress, re-enables findings, then finishes and closes again', async ({ page }) => {
      const world = await mockWorld(page, scenario, 'awaiting_closure')
      await open(page)
      await expect(button(page, '关闭活动')).toBeVisible()
      await expect(page.getByText('后才能新建发现项')).toBeVisible()
      expect(await page.getByRole('button', { name: '新建发现项' }).count()).toBe(0)

      await button(page, '恢复现场').click()
      const dialog = page.getByRole('dialog', { name: '恢复现场' })
      expect(world.posts).toHaveLength(0) // 提交前不发请求
      await dialog.getByLabel('恢复原因').fill('漏记一处缺陷')
      await dialog.getByRole('button', { name: '确认恢复' }).click()
      await expect(header(page).getByText('审查中', { exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: '新建发现项' })).toBeVisible()
      expect(await button(page, '恢复现场').count()).toBe(0)
      expect(await button(page, '关闭活动').count()).toBe(0)

      await invoke(page, COMMANDS[2])
      await expect(header(page).getByText('待关闭', { exact: true })).toBeVisible()
      await invoke(page, COMMANDS[3])
      await expect(header(page).getByText('已关闭', { exact: true })).toBeVisible()
      expect(world.posts).toEqual([
        { action: 'reopen_fieldwork', reason: '漏记一处缺陷' },
        { action: 'finish_fieldwork', reason: null },
        { action: 'close', reason: null },
      ])
    })

    test('cancel asks for a reason in a dialog and sends it', async ({ page }) => {
      const world = await mockWorld(page, scenario, 'scheduled')
      await open(page)
      await button(page, '取消活动').click()
      const dialog = page.getByRole('dialog', { name: '取消活动' })
      expect(world.posts).toHaveLength(0)
      await dialog.getByLabel('取消原因').fill('计划调整')
      await dialog.getByRole('button', { name: '确认取消' }).click()
      await expect(header(page).getByText('已取消', { exact: true })).toBeVisible()
      expect(world.posts).toEqual([{ action: 'cancel', reason: '计划调整' }])
    })
  })
}

// 每个命令的失败分类：409 / 422 / 403 / 结果未知。
for (const command of COMMANDS) {
  const from = NEXT[command.action].from
  const scenario: Scenario = command.action === 'close' || command.action === 'reopen_fieldwork' ? 'compliance_review' : 'process_review'

  test.describe(`${command.action} failures`, () => {
    test('409 says the state changed, refreshes silently and does not replay', async ({ page }) => {
      const world = await mockWorld(page, scenario, from)
      world.postStatus = 409
      world.postDetail = 'Concurrent ReviewCase transition'
      // 别人刚刚把活动推进到了另一个状态：刷新后命令集随之变化。
      world.lifecycleAfterFailure = from === 'draft' ? 'scheduled' : 'closed'
      await open(page)
      const readsBefore = world.caseReads
      await invoke(page, command)

      // 先等静默重读落地（命令集已按新状态变化），再断言提示：不依赖重读与断言之间的先后。
      await expect.poll(() => world.caseReads).toBeGreaterThan(readsBefore) // 静默重读，页面不回到加载态
      await expect(header(page).getByText(from === 'draft' ? '已排期' : '已关闭', { exact: true })).toBeVisible()
      if (command.action === 'reopen_fieldwork') {
        // 别人已把活动推进走：恢复现场不再可用，弹层随命令卸载，页面级提示保留。
        await expect(page.getByRole('dialog', { name: '恢复现场' })).toBeHidden()
        await expect(page.getByRole('status').filter({ hasText: '数据已变化' })).toBeVisible()
      } else if (command.action === 'cancel') {
        // 取消在新状态下仍然可用：弹层保留，显示 409 提示，并保留已填写的原因。
        const dialog = page.getByRole('dialog', { name: '取消活动' })
        await expect(dialog.getByText('数据已变化')).toBeVisible()
        await expect(dialog.getByLabel('取消原因')).toHaveValue('计划调整')
      } else {
        await expect(page.getByRole('status').filter({ hasText: '数据已变化' })).toBeVisible()
      }
      expect(world.posts).toHaveLength(1) // 不自动重放
    })

    test('422 shows the server message for the business rule', async ({ page }) => {
      const world = await mockWorld(page, scenario, from)
      world.postStatus = 422
      world.postDetail =
        command.action === 'cancel'
          ? 'Cancelling a ReviewCase requires a reason'
          : command.action === 'reopen_fieldwork'
            ? 'Reopening fieldwork requires a reason'
            : 'ReviewCase cannot close until every Finding is closed or voided'
      await open(page)
      await invoke(page, command)
      const where = command.dialog !== undefined && command.reasonLabel !== undefined ? page.getByRole('dialog', { name: command.dialog.title }) : commands(page)
      await expect(where.getByText(world.postDetail)).toBeVisible()
      expect(world.posts).toHaveLength(1)
      await expect(header(page).getByText(from === 'draft' ? '草稿' : from === 'scheduled' ? '已排期' : from === 'in_progress' ? '审查中' : '待关闭', { exact: true })).toBeVisible()
    })

    test('403 shows neutral copy without server details, and the case stays visible when it is still readable', async ({ page }) => {
      const world = await mockWorld(page, scenario, from)
      world.postStatus = 403
      world.postDetail = 'Missing role lead for transition_case'
      await open(page)
      await invoke(page, command)
      const where = command.dialog !== undefined && command.reasonLabel !== undefined ? page.getByRole('dialog', { name: command.dialog.title }) : commands(page)
      await expect(where.getByText('当前账号没有执行此操作的权限。')).toBeVisible()
      expect(await page.getByText('Missing role').count()).toBe(0)
      expect(world.posts).toHaveLength(1)
      await expect(page.getByRole('heading', { level: 1, name: 'Lifecycle Case' })).toBeVisible()
    })

    test('an unknown result is reported as unconfirmed, re-reads and never replays', async ({ page }) => {
      const world = await mockWorld(page, scenario, from)
      world.postStatus = 'abort'
      await open(page)
      const readsBefore = world.caseReads
      await invoke(page, command)
      const where = command.dialog !== undefined && command.reasonLabel !== undefined ? page.getByRole('dialog', { name: command.dialog.title }) : commands(page)
      await expect(where.getByText(/未确认.*是否成功/)).toBeVisible()
      await expect.poll(() => world.caseReads).toBeGreaterThan(readsBefore)
      expect(world.posts).toHaveLength(1)
    })
  })
}

test.describe('in-flight protection', () => {
  for (const command of COMMANDS.slice(0, 4)) {
    test(`${command.action}: double activation sends one request and disables the other commands while in flight`, async ({ page }) => {
      const from = NEXT[command.action].from
      const world = await mockWorld(page, 'process_review', from)
      let release: () => void = () => {}
      world.gate = new Promise<void>((resolve) => {
        release = resolve
      })
      await open(page)

      if (command.dialog === undefined) {
        await button(page, command.button).dblclick()
      } else {
        await button(page, command.button).click()
        const ok = page.getByRole('dialog', { name: command.dialog.title }).getByRole('button', { name: command.dialog.ok })
        await ok.dblclick()
      }
      await expect.poll(() => world.posts.length).toBe(1)
      for (const other of await commands(page).getByRole('button').all()) await expect(other).toBeDisabled()
      release()
      await expect(header(page).getByText(
        { schedule: '已排期', start: '审查中', finish_fieldwork: '待关闭', close: '已关闭' }[command.action] ?? '',
        { exact: true },
      )).toBeVisible()
      expect(world.posts).toHaveLength(1)
    })
  }

  test('reopen_fieldwork dialog: double submit sends one request and the dialog cannot be dismissed while in flight', async ({ page }) => {
    const world = await mockWorld(page, 'process_review', 'awaiting_closure')
    let release: () => void = () => {}
    world.gate = new Promise<void>((resolve) => {
      release = resolve
    })
    await open(page)
    await button(page, '恢复现场').click()
    const dialog = page.getByRole('dialog', { name: '恢复现场' })
    await dialog.getByLabel('恢复原因').fill('误操作')
    await dialog.getByRole('button', { name: '确认恢复' }).dblclick()
    await expect.poll(() => world.posts.length).toBe(1)
    await expect(dialog.getByRole('button', { name: /^取\s*消$/ })).toBeDisabled()
    for (const other of await commands(page).getByRole('button').all()) await expect(other).toBeDisabled()
    release()
    await expect(header(page).getByText('审查中', { exact: true })).toBeVisible()
    expect(world.posts).toEqual([{ action: 'reopen_fieldwork', reason: '误操作' }])
  })

  test('cancel dialog: double submit sends one request and the dialog cannot be dismissed while in flight', async ({ page }) => {
    const world = await mockWorld(page, 'compliance_review', 'draft')
    let release: () => void = () => {}
    world.gate = new Promise<void>((resolve) => {
      release = resolve
    })
    await open(page)
    await button(page, '取消活动').click()
    const dialog = page.getByRole('dialog', { name: '取消活动' })
    await dialog.getByLabel('取消原因').fill('计划调整')
    await dialog.getByRole('button', { name: '确认取消' }).dblclick()
    await expect.poll(() => world.posts.length).toBe(1)
    await expect(dialog.getByRole('button', { name: /^取\s*消$/ })).toBeDisabled()
    release()
    await expect(header(page).getByText('已取消', { exact: true })).toBeVisible()
    expect(world.posts).toHaveLength(1)
  })
})

test.describe('authorization loss', () => {
  test('a 403 on the command followed by a 403 re-read removes the case and its dialogs', async ({ page }) => {
    const world = await mockWorld(page, 'process_review', 'draft')
    world.postStatus = 403
    await open(page)
    await button(page, '取消活动').click()
    const dialog = page.getByRole('dialog', { name: '取消活动' })
    await dialog.getByLabel('取消原因').fill('计划调整')
    world.caseStatus = 403 // 提交之后再收回读权限：静默重读返回 403
    await dialog.getByRole('button', { name: '确认取消' }).click()
    await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
    expect(await page.getByRole('dialog').count()).toBe(0)
    expect(await page.getByRole('button', { name: '取消活动' }).count()).toBe(0)
  })

  test('an open confirmation dialog disappears when the case access is lost', async ({ page }) => {
    const world = await mockWorld(page, 'compliance_review', 'in_progress')
    world.postStatus = 403
    await open(page)
    await button(page, '完成现场工作').click()
    const dialog = page.getByRole('dialog', { name: '完成现场工作' })
    await expect(dialog).toBeVisible()
    world.caseStatus = 404
    await dialog.getByRole('button', { name: '确认完成' }).click()
    await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
    await expect(dialog).toBeHidden() // 确认框随 ready 分支卸载而销毁（含关闭动画）；该弹层之前确实可见
    expect(await page.getByRole('dialog').count()).toBe(0)
    expect(await page.getByRole('button', { name: '完成现场工作' }).count()).toBe(0)
  })
})

test('a command still in flight when the route switches to another case neither reports nor refreshes there', async ({ page }) => {
  const world = await mockWorld(page, 'process_review', 'draft')
  let release: () => void = () => {}
  world.gate = new Promise<void>((resolve) => {
    release = resolve
  })
  let otherReads = 0
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-other', (route) => {
    otherReads += 1
    return fulfillJson(route, 200, { ...caseBody(world), id: 'case-other', title: 'Other Case', lifecycle: 'draft' })
  })
  for (const child of ['findings', 'activities']) {
    await page.route((url) => url.pathname === `/api/v1/review-cases/case-other/${child}`, (route) => fulfillJson(route, 200, []))
  }
  await page.route((url) => url.pathname === '/api/v1/review-cases/case-other/members', (route) => fulfillJson(route, 200, []))
  await page.route((url) => url.pathname === '/api/v1/management/review-cases/case-other/progress', (route) =>
    fulfillJson(route, 404, { detail: 'Not found' }),
  )

  await open(page)
  await button(page, '安排活动').click()
  await expect.poll(() => world.posts.length).toBe(1)
  // 客户端路由切换（不重新加载页面）。测试 tsconfig 没有 DOM 类型，用字符串形式求值。
  await page.evaluate(
    "window.history.pushState({}, '', '/review-cases/case-other'); window.dispatchEvent(new PopStateEvent('popstate'))",
  )
  await expect(page.getByRole('heading', { level: 1, name: 'Other Case' })).toBeVisible()
  // 新活动没有继承旧命令的在途状态。
  await expect(button(page, '安排活动')).toBeEnabled()
  const readsAfterLoad = otherReads
  const responded = page.waitForResponse((response) => response.url().endsWith(`/review-cases/${CASE_ID}/transitions`))
  release()
  await responded
  // 旧命令的结果既不弹成功提示，也不改动新活动：以下两条是一次性断言，等响应落地后再看。
  await page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
  expect(await page.getByText('已完成：安排活动').count()).toBe(0)
  expect(otherReads).toBe(readsAfterLoad)
  await expect(header(page).getByText('草稿', { exact: true })).toBeVisible()
})

test('cancel 409 whose re-read makes cancel unavailable closes the dialog and keeps the notice on the page', async ({ page }) => {
  const world = await mockWorld(page, 'process_review', 'scheduled')
  world.postStatus = 409
  world.postDetail = 'Concurrent ReviewCase transition'
  world.lifecycleAfterFailure = 'in_progress'
  await open(page)
  await invoke(page, COMMANDS[4])
  await expect(header(page).getByText('审查中', { exact: true })).toBeVisible()
  await expect(page.getByRole('dialog', { name: '取消活动' })).toBeHidden() // 弹层之前确实打开过
  expect(await button(page, '取消活动').count()).toBe(0)
  await expect(page.getByRole('status').filter({ hasText: '数据已变化' })).toBeVisible()
  expect(world.posts).toHaveLength(1)
})
