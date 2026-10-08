import { expect, test, type Page, type Route } from '@playwright/test'

const admin = {
  id: '11111111-1111-1111-1111-111111111111',
  organization_id: '22222222-2222-2222-2222-222222222222',
  display_name: 'UI-6 Admin',
  platform_role: 'system_admin',
  primary_department_id: null,
  is_active: true,
}

const RESET_SUCCESS = '临时凭据已重置；目标用户下次登录必须修改密码。'
const TEMP_PASSWORD = 'temporary-password-123'
const API = '/api/v1/admin'

function fulfillJson(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

interface Harness {
  // 写操作之后的读取（刷新）先等待 gate，再按 refresh 返回。
  release: () => void
  writes: Array<{ method: string; path: string; body: unknown }>
  // 组织读取次数；写操作后增加说明发生了重新读取。
  reads: () => number
}

interface HarnessOptions {
  refresh?: 'ok' | { status: number }
  gated?: boolean
  // 对写操作的响应；默认按路径成功。
  write?: (route: Route, path: string, method: string) => Promise<void> | void
  // 用户列表；refreshed 为 true 表示写操作之后的重新读取。
  users?: (refreshed: boolean) => unknown[]
}

async function setup(page: Page, options: HarnessOptions = {}): Promise<Harness> {
  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  if (options.gated !== true) release()
  let organizationReads = 0
  const writes: Harness['writes'] = []

  await page.route((url) => url.pathname === '/api/v1/me', (route) =>
    fulfillJson(route, 200, { ...admin, must_change_password: false }),
  )
  await page.route((url) => url.pathname.startsWith(API), async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    if (method !== 'GET') {
      writes.push({ method, path, body: request.postDataJSON() })
      if (options.write !== undefined) return options.write(route, path, method)
      if (path.endsWith('/credential-reset')) return fulfillJson(route, 200, { id: 'user-1' })
      if (path === `${API}/departments`) return fulfillJson(route, 201, { id: 'dept-new', organization_id: 'o', name: 'New Dept', parent_id: null, is_active: true })
      return fulfillJson(route, 200, { id: 'user-1' })
    }
    if (path === `${API}/organization`) organizationReads += 1
    // 写操作之后的读取才是刷新（开发模式的 StrictMode 会让首次读取发两遍）。
    const isRefresh = writes.length > 0
    if (isRefresh) {
      await gate
      const refresh = options.refresh ?? 'ok'
      if (refresh !== 'ok') return fulfillJson(route, refresh.status, { detail: 'secret backend detail' })
    }
    const label = isRefresh ? 'Refreshed' : 'Initial'
    if (path === `${API}/organization`) return fulfillJson(route, 200, { id: 'org-1', name: `${label} Org`, is_active: true })
    if (path === `${API}/departments`) {
      return fulfillJson(route, 200, [
        { id: 'dept-1', organization_id: 'o', name: 'Audit Dept', parent_id: null, is_active: true },
      ])
    }
    if (path === `${API}/users`) {
      return fulfillJson(route, 200, options.users?.(isRefresh) ?? [
        { id: 'user-1', organization_id: 'o', display_name: `${label} User`, platform_role: 'ordinary_user', is_active: true, primary_department_id: 'dept-1' },
      ])
    }
    if (path === `${API}/scenario-status`) {
      return fulfillJson(route, 200, {
        items: [{
          scenario_key: 'process_review',
          display_name: '过程审查',
          is_active: true,
          versions: [{ scenario_version: 1, published_at: '2026-08-28T10:00:00Z', registry_present: true, ready: true }],
        }],
      })
    }
    return fulfillJson(route, 404, { detail: 'not found' })
  })
  return { release, writes, reads: () => organizationReads }
}

async function expectNoDocumentOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() => {
    const browser = globalThis as unknown as {
      document: { documentElement: { scrollWidth: number; clientWidth: number } }
    }
    return browser.document.documentElement.scrollWidth - browser.document.documentElement.clientWidth
  })).toBeLessThanOrEqual(1)
}

async function fillReset(page: Page, userName = 'Initial User') {
  await page.getByLabel('目标用户').click()
  // 已选中的值也带同名 title；下拉选项在后。
  await page.getByTitle(userName, { exact: true }).last().click()
  await page.getByLabel('临时密码').fill(TEMP_PASSWORD)
}

// 用户表格中的显示名称单元格（下拉框里同名的选项不算）。
function userCell(page: Page, name: string) {
  return page.getByRole('region', { name: '用户' }).getByRole('cell', { name, exact: true })
}

function confirmDialog(page: Page, title: string) {
  return page.getByRole('dialog', { name: title })
}

test('部门与用户通过抽屉创建，场景精确版本来自服务器', async ({ page }) => {
  const harness = await setup(page)
  await page.goto('/admin')

  await expect(page.getByRole('heading', { name: '管理设置', level: 1 })).toBeVisible()
  await expect(page.getByText('Initial Org · 启用')).toBeVisible()
  await expect(page.getByText('process_review@1 · 2026/08/28 18:00 · 代码已注册 · 可用')).toBeVisible()
  // 精确版本只出现一次，不再重复显示场景 key。
  expect(await page.getByText('process_review', { exact: false }).count()).toBe(1)
  await expect(page.getByText('组织启用')).toBeVisible()
  // 用户本来需要看的登录名之外，界面不出现内部 ID。
  expect(await page.getByText('user-1').count()).toBe(0)
  expect(await page.getByText('dept-1').count()).toBe(0)

  await page.getByRole('button', { name: '新建部门' }).click()
  const drawer = page.getByRole('dialog', { name: '新建部门' })
  await drawer.getByLabel('部门名称').fill('  New Dept ')
  await drawer.getByRole('button', { name: '创建部门' }).click()
  await expect(page.getByText('部门已创建。')).toBeVisible()
  await expect(drawer).toHaveCount(0)
  expect(harness.writes).toEqual([{ method: 'POST', path: `${API}/departments`, body: { name: 'New Dept', parent_id: null } }])

  await page.getByRole('button', { name: '新建用户' }).click()
  const userDrawer = page.getByRole('dialog', { name: '新建用户' })
  await userDrawer.getByRole('button', { name: '创建用户' }).click()
  await expect(userDrawer.getByText('请输入用户名称。')).toBeVisible()
  await expect(userDrawer.getByText('初始密码需要 12 至 1000 个字符。')).toBeVisible()
  expect(harness.writes).toHaveLength(1)

  await userDrawer.getByLabel('显示名称').fill('Created User')
  await userDrawer.getByLabel('登录名').fill('created-login')
  await userDrawer.getByLabel('初始密码').fill('initial-password-123')
  await userDrawer.getByLabel('主要部门').click()
  await page.getByTitle('Audit Dept', { exact: true }).click()
  await userDrawer.getByRole('button', { name: '创建用户' }).click()
  await expect(page.getByText('用户已创建。')).toBeVisible()
  expect(harness.writes[1]).toEqual({
    method: 'POST',
    path: `${API}/users`,
    body: {
      display_name: 'Created User',
      login_name: 'created-login',
      initial_password: 'initial-password-123',
      platform_role: 'ordinary_user',
      primary_department_id: 'dept-1',
      must_change_password: true,
    },
  })
})

test('停用用户需要二次确认，取消不发请求，确认后才提交', async ({ page }) => {
  const harness = await setup(page)
  await page.goto('/admin')
  await page.getByRole('button', { name: '编辑用户 Initial User' }).click()
  const drawer = page.getByRole('dialog', { name: '编辑用户' })
  await drawer.getByRole('checkbox', { name: '用户启用' }).uncheck()
  await drawer.getByRole('button', { name: '保存用户' }).click()

  const confirm = confirmDialog(page, '停用用户')
  await expect(confirm).toContainText('无法登录')
  await confirm.getByRole('button', { name: /^取\s*消$/ }).click()
  await expect(confirm).toHaveCount(0)
  expect(harness.writes).toHaveLength(0)
  await expect(drawer).toBeVisible()

  await drawer.getByRole('button', { name: '保存用户' }).click()
  await confirmDialog(page, '停用用户').getByRole('button', { name: '确认停用' }).click()
  await expect(page.getByText('用户已更新。')).toBeVisible()
  expect(harness.writes).toEqual([
    {
      method: 'PATCH',
      path: `${API}/users/user-1`,
      body: { display_name: 'Initial User', platform_role: 'ordinary_user', primary_department_id: 'dept-1', is_active: false },
    },
  ])
})

test('不停用用户的编辑直接提交，无需确认', async ({ page }) => {
  const harness = await setup(page)
  await page.goto('/admin')
  await page.getByRole('button', { name: '编辑用户 Initial User' }).click()
  const drawer = page.getByRole('dialog', { name: '编辑用户' })
  await drawer.getByLabel('显示名称').fill('Renamed User')
  await drawer.getByRole('button', { name: '保存用户' }).click()
  await expect(page.getByText('用户已更新。')).toBeVisible()
  expect(harness.writes).toHaveLength(1)
})

test('重置凭据需要二次确认；取消不发请求，确认后密码先清空再提交', async ({ page }) => {
  const harness = await setup(page)
  await page.goto('/admin')
  await fillReset(page)
  await page.getByRole('button', { name: '重置凭据' }).click()

  const confirm = confirmDialog(page, '重置凭据')
  await expect(confirm).toContainText('现有密码立即失效')
  await confirm.getByRole('button', { name: /^取\s*消$/ }).click()
  await expect(confirm).toHaveCount(0)
  expect(harness.writes).toHaveLength(0)

  await page.getByRole('button', { name: '重置凭据' }).click()
  await confirmDialog(page, '重置凭据').getByRole('button', { name: '确认重置' }).click()
  await expect(page.getByText(RESET_SUCCESS)).toBeVisible()
  await expect(page.getByLabel('临时密码')).toHaveValue('')
  expect(harness.writes).toEqual([
    { method: 'POST', path: `${API}/users/user-1/credential-reset`, body: { temporary_password: TEMP_PASSWORD } },
  ])
})

test('重置凭据遇到网络中断或 500：提示未确认，清空密码，只重新读取不重放', async ({ page }) => {
  let mode: 'abort' | 500 = 'abort'
  const harness = await setup(page, {
    write: (route) => (mode === 'abort' ? route.abort('connectionreset') : fulfillJson(route, 500, { detail: 'secret backend detail' })),
  })
  await page.goto('/admin')

  for (const next of ['abort', 500] as const) {
    mode = next
    const refreshed = harness.writes.length > 0
    if (refreshed) await expect(userCell(page, 'Refreshed User')).toBeVisible()
    const readsBefore = harness.reads()
    await fillReset(page, refreshed ? 'Refreshed User' : 'Initial User')
    await page.getByRole('button', { name: '重置凭据' }).click()
    await confirmDialog(page, '重置凭据').getByRole('button', { name: '确认重置' }).click()

    const alert = page.getByRole('alert').filter({ hasText: '未确认重置凭据是否成功' })
    await expect(alert).toContainText('临时密码已清空，重试需重新输入')
    await expect(page.getByLabel('临时密码')).toHaveValue('')
    expect(await page.getByText('secret backend detail').count()).toBe(0)
    await expect.poll(() => harness.reads()).toBeGreaterThan(readsBefore)
    await expect(page.getByRole('button', { name: '重置凭据' })).toBeEnabled()
  }
  // 每次用户操作恰好一次请求，没有自动重放。
  expect(harness.writes).toHaveLength(2)
})

test('结果未知后重新读取也失败：保留未确认提示，成功提示不残留', async ({ page }) => {
  const harness = await setup(page, {
    refresh: { status: 500 },
    write: (route) => route.abort('connectionreset'),
  })
  await page.goto('/admin')
  await fillReset(page)
  await page.getByRole('button', { name: '重置凭据' }).click()
  await confirmDialog(page, '重置凭据').getByRole('button', { name: '确认重置' }).click()

  await expect(page.getByRole('alert').filter({ hasText: '请求失败（状态码 500）。' })).toBeVisible()
  await expect(page.getByRole('alert').filter({ hasText: '未确认重置凭据是否成功' })).toBeVisible()
  expect(await page.getByText('Initial Org').count()).toBe(0)
  expect(harness.writes).toHaveLength(1)
})

test('刷新期间区块显示 Spin、旧内容与成功提示保持，刷新后提示仍在', async ({ page }) => {
  const harness = await setup(page, { gated: true })
  await page.goto('/admin')
  await expect(userCell(page, 'Initial User')).toBeVisible()

  await fillReset(page)
  await page.getByRole('button', { name: '重置凭据' }).click()
  await confirmDialog(page, '重置凭据').getByRole('button', { name: '确认重置' }).click()

  await expect(page.getByText('正在刷新')).toBeVisible()
  await expect(page.getByText(RESET_SUCCESS)).toBeVisible()
  await expect(userCell(page, 'Initial User')).toBeVisible()
  expect(await userCell(page, 'Refreshed User').count()).toBe(0)
  await expect(page.getByLabel('临时密码')).toHaveValue('')

  harness.release()
  await expect(userCell(page, 'Refreshed User')).toBeVisible()
  await expect(page.getByText('正在刷新')).toHaveCount(0)
  await expect(page.getByText(RESET_SUCCESS)).toBeVisible()
})

test('部门创建的成功提示同样在刷新期间保持', async ({ page }) => {
  const harness = await setup(page, { gated: true })
  await page.goto('/admin')
  await page.getByRole('button', { name: '新建部门' }).click()
  const drawer = page.getByRole('dialog', { name: '新建部门' })
  await drawer.getByLabel('部门名称').fill('New Dept')
  await drawer.getByRole('button', { name: '创建部门' }).click()

  await expect(page.getByText('正在刷新')).toBeVisible()
  await expect(page.getByText('部门已创建。')).toBeVisible()
  harness.release()
  await expect(userCell(page, 'Refreshed User')).toBeVisible()
  await expect(page.getByText('部门已创建。')).toBeVisible()
})

const userRow = (id: string, name: string, role = 'ordinary_user') => ({
  id, organization_id: 'o', display_name: name, platform_role: role, is_active: true, primary_department_id: 'dept-1',
})

// 同一任务里先关闭再打开：模拟关闭动画结束前就切换目标。
async function closeThenOpen(page: Page, drawerName: string, nextButton: string) {
  const drawer = page.getByRole('dialog', { name: drawerName })
  const cancel = await drawer.getByRole('button', { name: /^取\s*消$/ }).elementHandle()
  const next = await page.getByRole('button', { name: nextButton }).elementHandle()
  await page.evaluate(([close, open]) => {
    ;(close as unknown as { click: () => void }).click()
    ;(open as unknown as { click: () => void }).click()
  }, [cancel, next])
}

test('关闭“编辑 A”后立即打开“编辑 B”：表单是 B 的值，保存写给 B', async ({ page }) => {
  const harness = await setup(page, { users: () => [userRow('user-a', 'Alpha User'), userRow('user-b', 'Beta User')] })
  await page.goto('/admin')
  await page.getByRole('button', { name: '编辑用户 Alpha User' }).click()
  const drawer = page.getByRole('dialog', { name: '编辑用户' })
  await drawer.getByLabel('显示名称').fill('Alpha Edited')
  await closeThenOpen(page, '编辑用户', '编辑用户 Beta User')

  await expect(drawer.getByLabel('显示名称')).toHaveValue('Beta User')
  await drawer.getByRole('button', { name: '保存用户' }).click()
  await expect(page.getByText('用户已更新。')).toBeVisible()
  expect(harness.writes).toEqual([
    {
      method: 'PATCH',
      path: `${API}/users/user-b`,
      body: { display_name: 'Beta User', platform_role: 'ordinary_user', primary_department_id: 'dept-1', is_active: true },
    },
  ])
})

test('关闭“编辑部门”后立即“新建部门”：表单为空，提交是创建而不是更新', async ({ page }) => {
  const harness = await setup(page)
  await page.goto('/admin')
  await page.getByRole('button', { name: '编辑部门 Audit Dept' }).click()
  const edit = page.getByRole('dialog', { name: '编辑部门' })
  await expect(edit.getByLabel('部门名称')).toHaveValue('Audit Dept')
  await closeThenOpen(page, '编辑部门', '新建部门')

  const drawer = page.getByRole('dialog', { name: '新建部门' })
  await expect(drawer.getByLabel('部门名称')).toHaveValue('')
  await drawer.getByLabel('部门名称').fill('Fresh Dept')
  await drawer.getByRole('button', { name: '创建部门' }).click()
  await expect(page.getByText('部门已创建。')).toBeVisible()
  expect(harness.writes).toEqual([{ method: 'POST', path: `${API}/departments`, body: { name: 'Fresh Dept', parent_id: null } }])
})

test('同一目标再次打开是新的编辑会话，不带上次未保存的内容', async ({ page }) => {
  await setup(page)
  await page.goto('/admin')
  await page.getByRole('button', { name: '编辑部门 Audit Dept' }).click()
  const drawer = page.getByRole('dialog', { name: '编辑部门' })
  await drawer.getByLabel('部门名称').fill('Unsaved')
  await closeThenOpen(page, '编辑部门', '编辑部门 Audit Dept')
  await expect(drawer.getByLabel('部门名称')).toHaveValue('Audit Dept')
})

async function triggerGatedRefresh(page: Page) {
  await page.getByRole('button', { name: '新建部门' }).click()
  const drawer = page.getByRole('dialog', { name: '新建部门' })
  await drawer.getByLabel('部门名称').fill('Trigger Dept')
  await drawer.getByRole('button', { name: '创建部门' }).click()
  await expect(page.getByText('正在刷新')).toBeVisible()
}

async function expectContentRemoved(page: Page, status: number) {
  if (status === 403) await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  else await expect(page.getByRole('alert').filter({ hasText: '请求失败（状态码 500）。' })).toBeVisible()
}

for (const status of [403, 500]) {
  test(`重置确认框打开时刷新返回 ${status}：确认框消失，不发写请求`, async ({ page }) => {
    const harness = await setup(page, { gated: true, refresh: { status } })
    await page.goto('/admin')
    await fillReset(page)
    await triggerGatedRefresh(page)

    // 刷新期间遮罩会拦截指针，用键盘打开确认框。
    await page.getByRole('button', { name: '重置凭据' }).press('Enter')
    const confirm = confirmDialog(page, '重置凭据')
    await expect(confirm).toBeVisible()
    harness.release()

    await expectContentRemoved(page, status)
    await expect(confirm).toHaveCount(0)
    expect(harness.writes).toHaveLength(1)
  })

  test(`停用确认框打开时刷新返回 ${status}：抽屉与确认框都消失，不发写请求`, async ({ page }) => {
    const harness = await setup(page, { gated: true, refresh: { status } })
    await page.goto('/admin')
    await triggerGatedRefresh(page)

    await page.getByRole('button', { name: '编辑用户 Initial User' }).press('Enter')
    const drawer = page.getByRole('dialog', { name: '编辑用户' })
    await drawer.getByRole('checkbox', { name: '用户启用' }).uncheck()
    await drawer.getByRole('button', { name: '保存用户' }).click()
    const confirm = confirmDialog(page, '停用用户')
    await expect(confirm).toBeVisible()
    harness.release()

    await expectContentRemoved(page, status)
    await expect(confirm).toHaveCount(0)
    await expect(drawer).toHaveCount(0)
    expect(harness.writes).toHaveLength(1)
  })
}

test('刷新后编辑目标消失：抽屉随之关闭，不再提交旧目标', async ({ page }) => {
  const harness = await setup(page, {
    gated: true,
    users: (refreshed) => (refreshed ? [userRow('user-b', 'Beta User')] : [userRow('user-a', 'Alpha User'), userRow('user-b', 'Beta User')]),
  })
  await page.goto('/admin')
  await triggerGatedRefresh(page)

  await page.getByRole('button', { name: '编辑用户 Alpha User' }).press('Enter')
  const drawer = page.getByRole('dialog', { name: '编辑用户' })
  await expect(drawer).toBeVisible()
  harness.release()
  await expect(userCell(page, 'Beta User')).toBeVisible()
  await expect(drawer).toHaveCount(0)
  expect(harness.writes).toHaveLength(1)
})

test('抽屉写操作结果未知且重新读取也失败：页面级保留“未确认”提示与密码已清空说明', async ({ page }) => {
  const harness = await setup(page, { refresh: { status: 500 }, write: (route) => route.abort('connectionreset') })
  await page.goto('/admin')
  await page.getByRole('button', { name: '新建用户' }).click()
  const drawer = page.getByRole('dialog', { name: '新建用户' })
  await drawer.getByLabel('显示名称').fill('X User')
  await drawer.getByLabel('登录名').fill('x-login')
  await drawer.getByLabel('初始密码').fill('initial-password-123')
  await drawer.getByRole('button', { name: '创建用户' }).click()

  await expect(page.getByRole('alert').filter({ hasText: '请求失败（状态码 500）。' })).toBeVisible()
  const unknown = page.getByRole('alert').filter({ hasText: '未确认创建用户是否成功' })
  await expect(unknown).toBeVisible()
  await expect(unknown).toContainText('初始密码已清空')
  expect(harness.writes).toHaveLength(1)
})

test('新操作或打开编辑会清除页面级提示', async ({ page }) => {
  let fail = true
  let seen!: () => void
  let requestSeen = new Promise<void>((resolve) => { seen = resolve })
  let release!: () => void
  let held = Promise.resolve()
  await setup(page, {
    write: async (route) => {
      if (fail) return route.abort('connectionreset')
      seen()
      await held
      return fulfillJson(route, 200, { id: 'user-1' })
    },
  })
  await page.goto('/admin')
  const unknown = page.getByRole('alert').filter({ hasText: '未确认重置凭据是否成功' })
  const resetOnce = async (name: string) => {
    await fillReset(page, name)
    await page.getByRole('button', { name: '重置凭据' }).click()
    await confirmDialog(page, '重置凭据').getByRole('button', { name: '确认重置' }).click()
  }

  await resetOnce('Initial User')
  await expect(unknown).toBeVisible()
  // 重新读取之后用户名变为 Refreshed User。
  await expect(userCell(page, 'Refreshed User')).toBeVisible()
  await page.getByRole('button', { name: '编辑用户 Refreshed User' }).click()
  const drawer = page.getByRole('dialog', { name: '编辑用户' })
  await expect(drawer).toBeVisible()
  expect(await unknown.count()).toBe(0)
  await drawer.getByRole('button', { name: /^取\s*消$/ }).click()
  await expect(drawer).toHaveCount(0)

  // 再制造一次未知结果，然后发起一个被拦住的新操作：提示在请求完成前就已被清除。
  await resetOnce('Refreshed User')
  await expect(unknown).toBeVisible()
  fail = false
  held = new Promise<void>((resolve) => { release = resolve })
  requestSeen = new Promise<void>((resolve) => { seen = resolve })
  await resetOnce('Refreshed User')
  await requestSeen
  expect(await unknown.count()).toBe(0)
  release()
  await expect(page.getByText(RESET_SUCCESS)).toBeVisible()
})

test('管理员把自己降为普通用户需要二次确认；降级他人不需要', async ({ page }) => {
  const harness = await setup(page, {
    users: () => [userRow(admin.id, 'UI-6 Admin', 'system_admin'), userRow('user-b', 'Other Admin', 'system_admin')],
  })
  await page.goto('/admin')

  await page.getByRole('button', { name: '编辑用户 UI-6 Admin' }).click()
  const drawer = page.getByRole('dialog', { name: '编辑用户' })
  await drawer.getByLabel('平台角色').click()
  await page.getByTitle('普通用户', { exact: true }).last().click()
  await drawer.getByRole('button', { name: '保存用户' }).click()
  const confirm = confirmDialog(page, '降低自己的管理权限')
  await expect(confirm).toContainText('无法自行撤销')
  await confirm.getByRole('button', { name: /^取\s*消$/ }).click()
  await expect(confirm).toHaveCount(0)
  expect(harness.writes).toHaveLength(0)

  await drawer.getByRole('button', { name: '保存用户' }).click()
  await confirmDialog(page, '降低自己的管理权限').getByRole('button', { name: '确认降权' }).click()
  await expect(page.getByText('用户已更新。')).toBeVisible()
  expect(harness.writes).toEqual([
    {
      method: 'PATCH',
      path: `${API}/users/${admin.id}`,
      body: { display_name: 'UI-6 Admin', platform_role: 'ordinary_user', primary_department_id: 'dept-1', is_active: true },
    },
  ])

  await expect(drawer).toHaveCount(0)
  await page.getByRole('button', { name: '编辑用户 Other Admin' }).click()
  await drawer.getByLabel('平台角色').click()
  await page.getByTitle('普通用户', { exact: true }).last().click()
  await drawer.getByRole('button', { name: '保存用户' }).click()
  await expect(page.getByText('用户已更新。')).toBeVisible()
  expect(harness.writes).toHaveLength(2)
})

for (const status of [401, 403, 404]) {
  test(`刷新返回 ${status} 时立即移除受保护内容，只给中性提示`, async ({ page }) => {
    const harness = await setup(page, { gated: true, refresh: { status } })
    await page.goto('/admin')
    await expect(userCell(page, 'Initial User')).toBeVisible()
    await fillReset(page)
    await page.getByRole('button', { name: '重置凭据' }).click()
    await confirmDialog(page, '重置凭据').getByRole('button', { name: '确认重置' }).click()
    await expect(page.getByText('正在刷新')).toBeVisible()
    harness.release()

    // 401 由全局会话处理离开本页；403/404 在本页以中性 Result 呈现。
    if (status !== 401) await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
    else await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
    const main = page.getByRole('main')
    expect(await main.getByText('Initial User').count()).toBe(0)
    expect(await main.getByText('Initial Org').count()).toBe(0)
    // 提示的退出有动画，用可重试断言等它离开 DOM。
    await expect(page.getByText(RESET_SUCCESS)).toHaveCount(0)
    expect(await page.getByText('secret backend detail').count()).toBe(0)
    expect(await page.getByRole('button', { name: '重置凭据' }).count()).toBe(0)
  })
}

test('刷新返回 500：移除内容与成功提示，显示读取失败并可重新加载', async ({ page }) => {
  const harness = await setup(page, { gated: true, refresh: { status: 500 } })
  await page.goto('/admin')
  await expect(userCell(page, 'Initial User')).toBeVisible()
  await fillReset(page)
  await page.getByRole('button', { name: '重置凭据' }).click()
  await confirmDialog(page, '重置凭据').getByRole('button', { name: '确认重置' }).click()
  await expect(page.getByText('正在刷新')).toBeVisible()
  harness.release()

  await expect(page.getByRole('alert').filter({ hasText: '请求失败（状态码 500）。' })).toBeVisible()
  expect(await page.getByRole('main').getByText('Initial User').count()).toBe(0)
  await expect(page.getByText(RESET_SUCCESS)).toHaveCount(0)
  await expect(page.getByRole('button', { name: '重新加载' })).toBeVisible()
})

test('写操作 403：操作区中性提示、不显示后端 detail，并重新校验授权', async ({ page }) => {
  let deniedOnRead = false
  const harness = await setup(page, {
    write: (route) => {
      deniedOnRead = true
      return fulfillJson(route, 403, { detail: 'Role system_admin required' })
    },
  })
  await page.goto('/admin')
  await page.getByRole('button', { name: '新建部门' }).click()
  const readsBefore = harness.reads()
  const drawer = page.getByRole('dialog', { name: '新建部门' })
  await drawer.getByLabel('部门名称').fill('Blocked Dept')
  await drawer.getByRole('button', { name: '创建部门' }).click()

  await expect(drawer.getByText('当前账号没有执行此操作的权限。')).toBeVisible()
  await expect(drawer.getByLabel('部门名称')).toHaveValue('Blocked Dept')
  expect(await page.getByText('Role system_admin required').count()).toBe(0)
  await expect.poll(() => harness.reads()).toBeGreaterThan(readsBefore)
  expect(deniedOnRead).toBe(true)
})

test('抽屉里 422 与 409 不展示后端原文', async ({ page }) => {
  let status = 422
  const harness = await setup(page, {
    write: (route) =>
      fulfillJson(
        route,
        status,
        status === 422
          ? { detail: 'initial_password: contains secret-echo', code: 'password.too_short', params: { min: 12 }, errors: [] }
          : { detail: 'initial_password: contains secret-echo' },
      ),
  })
  await page.goto('/admin')
  await page.getByRole('button', { name: '新建用户' }).click()
  const drawer = page.getByRole('dialog', { name: '新建用户' })
  await drawer.getByLabel('显示名称').fill('X User')
  await drawer.getByLabel('登录名').fill('x-login')
  await drawer.getByLabel('初始密码').fill('initial-password-123')
  await drawer.getByRole('button', { name: '创建用户' }).click()

  await expect(drawer.getByText('密码长度不足，至少需要 12 个字符。')).toBeVisible()
  await expect(drawer.getByLabel('初始密码')).toHaveValue('')
  await expect(drawer.getByLabel('显示名称')).toHaveValue('X User')
  expect(await page.getByText('secret-echo').count()).toBe(0)

  status = 409
  await drawer.getByLabel('初始密码').fill('initial-password-123')
  await drawer.getByRole('button', { name: '创建用户' }).click()
  await expect(drawer.getByText('数据已变化，正在获取最新状态')).toBeVisible()
  expect(await page.getByText('secret-echo').count()).toBe(0)
  expect(harness.writes).toHaveLength(2)
})

for (const width of [375, 320]) {
  test(`${width}px 无页面级横向溢出，表格横向滚动，抽屉全宽`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await setup(page)
    await page.goto('/admin')
    await expect(page.getByRole('heading', { name: '管理设置', level: 1 })).toBeVisible()
    await expect(userCell(page, 'Initial User')).toBeVisible()
    await expectNoDocumentOverflow(page)

    await page.getByRole('button', { name: '编辑用户 Initial User' }).click()
    const drawer = page.getByRole('dialog', { name: '编辑用户' })
    await expect(drawer.getByRole('button', { name: '保存用户' })).toBeVisible()
    await expectNoDocumentOverflow(page)
    await drawer.getByRole('button', { name: /^取\s*消$/ }).click()
    await expect(drawer).toHaveCount(0)

    await fillReset(page)
    await expectNoDocumentOverflow(page)
  })
}
